
from dataclasses import dataclass

from space import agents
from space.core.models import Agent, Spawn
from space.core.types import AgentId

from . import trace
from .repo import fetch


@dataclass
class LogEntry:
    id: str
    agent_id: AgentId
    agent_identity: str
    agent_handle: str
    source: str
    status: str
    created_at: str | None
    last_active_at: str | None
    duration_seconds: int | None
    summary: str | None
    error: str | None
    primitives: dict[str, dict[str, int]]


def log(
    agent_id: AgentId | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[LogEntry]:
    spawn_list = fetch(
        agent_id=agent_id,
        since=since,
        limit=limit,
    )
    spawn_list = list(reversed(spawn_list))

    agent_ids = list({s.agent_id for s in spawn_list})
    agent_map = agents.batch_get(agent_ids)

    return [_to_entry(s, agent_map) for s in spawn_list]


def _to_entry(s: Spawn, agent_map: dict[AgentId, Agent]) -> LogEntry:
    agent = agent_map.get(s.agent_id)
    handle = agent.handle if agent else s.agent_id[:8]
    identity = (agent.identity or agent.handle) if agent else s.agent_id[:8]

    duration_f = trace.spawn_duration(s)
    duration = int(duration_f) if duration_f is not None else None
    analysis = trace.analyze(s.id)
    primitives = {k: {"r": v.read, "w": v.write} for k, v in analysis.primitives.items()}

    return LogEntry(
        id=s.id[:8],
        agent_id=s.agent_id,
        agent_identity=identity,
        agent_handle=handle,
        source="cli",
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        created_at=s.created_at,
        last_active_at=s.last_active_at,
        duration_seconds=duration,
        summary=s.summary,
        error=s.error,
        primitives=primitives,
    )
