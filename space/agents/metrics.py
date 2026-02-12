from dataclasses import dataclass

from space.core.models import Agent
from space.core.types import SpawnId
from space.lib import store


@dataclass
class ActiveSpawn:
    id: SpawnId


@dataclass
class AgentStats:
    message_count: int
    spawn_count: int
    spawns_by_status: dict[str, int]


@dataclass
class AgentActivity:
    active_spawns: list[ActiveSpawn]
    last_active: str | None


@dataclass
class AgentSummary:
    handle: str
    messages: int
    spawns: int


def stats(agent: Agent) -> AgentStats:
    message_count = 0
    spawn_count = 0
    spawns_by_status: dict[str, int] = {}
    with store.ensure() as conn:
        message_count = conn.execute(
            "SELECT COUNT(*) FROM replies WHERE author_id = ?",
            (agent.id,),
        ).fetchone()[0]
        spawn_count = conn.execute(
            "SELECT COUNT(*) FROM spawns WHERE agent_id = ?", (agent.id,)
        ).fetchone()[0]

        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM spawns WHERE agent_id = ? GROUP BY status",
            (agent.id,),
        ).fetchall()
        for row in status_rows:
            spawns_by_status[row[0]] = row[1]

    return AgentStats(
        message_count=message_count,
        spawn_count=spawn_count,
        spawns_by_status=spawns_by_status,
    )


def all_stats() -> list[AgentSummary]:
    with store.ensure() as conn:
        rows = conn.execute(
            """SELECT
                a.handle,
                (SELECT COUNT(*) FROM replies WHERE author_id = a.id) as messages,
                (SELECT COUNT(*) FROM spawns WHERE agent_id = a.id) as spawns
            FROM agents a
            WHERE a.type = 'ai' AND a.archived_at IS NULL
            ORDER BY messages DESC"""
        ).fetchall()
    return [AgentSummary(handle=r[0], messages=r[1], spawns=r[2]) for r in rows]


def activity(agent: Agent) -> AgentActivity:
    active_spawns: list[ActiveSpawn] = []
    last_active: str | None = None
    with store.ensure() as conn:
        active_spawns_rows = conn.execute(
            """SELECT s.id
               FROM spawns s
               WHERE s.agent_id = ? AND s.status = 'active'
               ORDER BY s.created_at DESC""",
            (agent.id,),
        ).fetchall()

        active_spawns = [ActiveSpawn(id=row[0]) for row in active_spawns_rows]

        last_active_row = conn.execute(
            "SELECT MAX(created_at) FROM spawns WHERE agent_id = ?", (agent.id,)
        ).fetchone()
        last_active = last_active_row[0] if last_active_row else None

    return AgentActivity(active_spawns=active_spawns, last_active=last_active)


@dataclass
class SilentAgent:
    handle: str
    last_activity: str | None
    hours_silent: float | None


def silent_agents(hours: int = 24) -> list[SilentAgent]:
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT a.handle, MAX(act.created_at) as last_activity,
                   ROUND((julianday('now') - julianday(MAX(act.created_at))) * 24, 1) as hours_silent
            FROM agents a
            LEFT JOIN activity act ON a.id = act.agent_id
              AND act.created_at > datetime('now', ? || ' hours')
            WHERE a.type = 'ai' AND a.model IS NOT NULL AND a.archived_at IS NULL
            GROUP BY a.id
            HAVING MAX(act.created_at) IS NULL OR hours_silent > ?
            ORDER BY hours_silent DESC NULLS FIRST
            """,
            (f"-{hours}", hours / 2),
        ).fetchall()
    return [SilentAgent(handle=r[0], last_activity=r[1], hours_silent=r[2]) for r in rows]
