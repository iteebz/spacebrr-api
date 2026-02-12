import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from space import agents
from space.agents import identity, spawn
from space.core.models import SpawnStatus
from space.ledger import projects
from space.lib import store

logger = logging.getLogger(__name__)


def swarm_age() -> int:
    with store.ensure() as conn:
        row = conn.execute("SELECT MIN(created_at) FROM agents").fetchone()
        if not row or not row[0]:
            return 0
        try:
            genesis = datetime.fromisoformat(row[0])
            if genesis.tzinfo is None:
                genesis = genesis.replace(tzinfo=UTC)
            delta = datetime.now(UTC) - genesis
            return max(0, delta.days)
        except Exception:
            return 0


def _last_artifacts(agent_ids: list[str]) -> dict[str, tuple[str, str, str]]:
    if not agent_ids:
        return {}
    placeholders = ",".join("?" * len(agent_ids))
    with store.ensure() as conn:
        rows = conn.execute(
            f"""
            SELECT agent_id, type, id, content FROM (
                SELECT agent_id, 'i' as type, id, content, created_at
                FROM insights WHERE agent_id IN ({placeholders}) AND deleted_at IS NULL
                UNION ALL
                SELECT agent_id, 'd' as type, id, content, created_at
                FROM decisions WHERE agent_id IN ({placeholders}) AND deleted_at IS NULL
                UNION ALL
                SELECT assignee_id as agent_id, 't' as type, id, content, created_at
                FROM tasks WHERE assignee_id IN ({placeholders}) AND deleted_at IS NULL
                UNION ALL
                SELECT author_id as agent_id, 'r' as type, id, content, created_at
                FROM replies WHERE author_id IN ({placeholders}) AND deleted_at IS NULL
            )
            WHERE agent_id IN ({placeholders})
            GROUP BY agent_id
            HAVING created_at = MAX(created_at)
            """,  # noqa: S608
            agent_ids * 5,
        ).fetchall()
    return {r[0]: (r[1], r[2][:8], r[3]) for r in rows}


def live() -> list[dict[str, Any]]:
    all_agents = agents.fetch(type="ai")
    if not all_agents:
        return []

    active = spawn.fetch(status=SpawnStatus.ACTIVE)
    active_by_agent = {s.agent_id: s for s in active}
    last_active_map = agents.batch_last_active([a.id for a in all_agents])

    agent_ids = [str(a.id) for a in all_agents]
    artifact_map = _last_artifacts(agent_ids)

    desc_map: dict[str, str] = {}
    for a in all_agents:
        if a.identity:
            try:
                c = identity.load(a.identity)
                if c.description:
                    desc_map[a.id] = c.description
            except Exception:
                logger.debug("failed to load identity for %s", a.handle)

    result = []
    for agent in all_agents:
        active_spawn = active_by_agent.get(agent.id)

        if active_spawn:
            usage_data = spawn.usage(active_spawn)
            if usage_data:
                used_pct = usage_data.get("percentage", 0)
                health_pct = max(0, 100 - used_pct)
            else:
                health_pct = None
            agent_status = "active"
        else:
            health_pct = None
            agent_status = "idle"

        artifact = artifact_map.get(agent.id)
        artifact_str = f"{artifact[0]}/{artifact[1]}: {artifact[2]}" if artifact else ""

        cwd = spawn.extract_last_cwd(active_spawn.id) if active_spawn else None
        git_root = projects.find_git_root(Path(cwd)) if cwd else None
        project = projects.find_by_path(git_root) if git_root else None

        result.append(
            {
                "handle": agent.handle,
                "health": round(health_pct, 0) if health_pct is not None else None,
                "status": agent_status,
                "artifact": artifact_str,
                "description": desc_map.get(agent.id, ""),
                "last_active": last_active_map.get(agent.id),
                "spawn_id": active_spawn.id[:8] if active_spawn else None,
                "cwd": cwd,
                "project": project.name if project else None,
            }
        )

    result.sort(key=lambda x: (x["status"] != "active", x["handle"]))  # type: ignore[reportUnknownLambdaType]
    return result


def snapshot() -> dict[str, Any]:
    with store.ensure() as conn:
        active_spawns = conn.execute(
            """
            SELECT a.handle, COUNT(*) as count
            FROM spawns s
            JOIN agents a ON s.agent_id = a.id
            WHERE s.status = 'active'
            GROUP BY a.handle
            ORDER BY count DESC
            """
        ).fetchall()

        active_tasks = conn.execute(
            """
            SELECT t.id, t.content, a.handle
            FROM tasks t
            JOIN agents a ON t.assignee_id = a.id
            WHERE t.status = 'active' AND t.deleted_at IS NULL
            ORDER BY t.started_at DESC
            """
        ).fetchall()

        committed = conn.execute(
            """
            SELECT d.id, d.content, a.handle, d.reversible
            FROM decisions d
            JOIN agents a ON d.agent_id = a.id
            WHERE d.committed_at IS NOT NULL
              AND d.actioned_at IS NULL AND d.rejected_at IS NULL
              AND d.deleted_at IS NULL AND d.archived_at IS NULL
            ORDER BY d.committed_at DESC
            LIMIT 5
            """
        ).fetchall()

        open_q = conn.execute(
            """
            SELECT i.id, i.content, a.handle
            FROM insights i
            JOIN agents a ON i.agent_id = a.id
            WHERE i.open = 1 AND i.deleted_at IS NULL AND i.archived_at IS NULL
            ORDER BY i.created_at DESC
            LIMIT 3
            """
        ).fetchall()

        recent_insights = conn.execute(
            """
            SELECT i.id, i.domain, i.content, a.handle
            FROM insights i
            JOIN agents a ON i.agent_id = a.id
            WHERE i.deleted_at IS NULL AND i.archived_at IS NULL
            ORDER BY i.created_at DESC
            LIMIT 8
            """
        ).fetchall()

        recent = conn.execute(
            """
            SELECT s.id, a.handle, s.summary
            FROM spawns s
            JOIN agents a ON s.agent_id = a.id
            WHERE s.summary IS NOT NULL AND s.status = 'done'
            ORDER BY s.last_active_at DESC
            LIMIT 5
            """
        ).fetchall()

    return {
        "spawns": [{"agent": r[0], "count": r[1]} for r in active_spawns],
        "active": [{"id": r[0][:8], "content": r[1], "agent": r[2]} for r in active_tasks],
        "committed": [
            {
                "id": r[0][:8],
                "content": r[1][:60] if len(r[1]) > 60 else r[1],
                "agent": r[2],
                "reversible": r[3],
            }
            for r in committed
        ],
        "questions": [{"id": r[0][:8], "content": r[1], "agent": r[2]} for r in open_q],
        "insights": [
            {"id": r[0][:8], "domain": r[1] or "", "content": r[2], "agent": r[3]}
            for r in recent_insights
        ],
        "recent": [{"id": r[0][:8], "agent": r[1], "summary": r[2]} for r in recent],
    }
