from typing import Any

from space.lib import store

from .swarm import artifacts_per_spawn, compounding


def _artifacts_at(at: str, hours: int) -> list[dict[str, Any]]:
    """Calculate artifacts/spawn ratio per agent around a timestamp."""
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                a.handle,
                COUNT(DISTINCT act.spawn_id) as spawn_count,
                COUNT(act.id) as artifact_count,
                ROUND(CAST(COUNT(act.id) AS FLOAT) / NULLIF(COUNT(DISTINCT act.spawn_id), 0), 2) as ratio
            FROM activity act
            JOIN agents a ON act.agent_id = a.id
            WHERE act.spawn_id IS NOT NULL
              AND act.created_at BETWEEN datetime(?, ? || ' hours') AND ?
              AND act.action = 'created'
            GROUP BY a.handle
            ORDER BY ratio DESC
            """,
            (at, f"-{hours}", at),
        ).fetchall()
    return [{"agent": r[0], "spawns": r[1], "artifacts": r[2], "ratio": r[3]} for r in rows]


def _compounding_at(at: str, hours: int = 168) -> dict[str, Any]:
    """Measure compounding in a window ending at timestamp (via citations table)."""
    with store.ensure() as conn:
        total = conn.execute(
            """
            SELECT COUNT(*) FROM insights
            WHERE deleted_at IS NULL AND archived_at IS NULL
              AND created_at BETWEEN datetime(?, ? || ' hours') AND ?
            """,
            (at, f"-{hours}", at),
        ).fetchone()[0]
        referencing = conn.execute(
            """
            SELECT COUNT(DISTINCT i.id) FROM insights i
            JOIN citations c ON c.source_type = 'insight' AND c.source_id = i.id
            WHERE i.deleted_at IS NULL AND i.archived_at IS NULL
              AND i.created_at BETWEEN datetime(?, ? || ' hours') AND ?
            """,
            (at, f"-{hours}", at),
        ).fetchone()[0]
    rate = round(referencing / total * 100, 1) if total else 0
    return {"window_hours": hours, "total": total, "referencing": referencing, "rate": rate}


def rsi_comparison(commit_ts: str, hours: int = 24) -> dict[str, Any]:
    """Compare stats before and after an RSI commit."""
    before = {
        "artifacts_per_spawn": _artifacts_at(commit_ts, hours),
        "compounding": _compounding_at(commit_ts),
    }
    after = {
        "artifacts_per_spawn": artifacts_per_spawn(hours),
        "compounding": compounding(),
    }
    return {"commit_ts": commit_ts, "hours": hours, "before": before, "after": after}
