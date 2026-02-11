"""Crash recovery: resume spawns with existing sessions."""

import logging

from space import agents
from space.agents import spawn
from space.core.models import Spawn, SpawnMode
from space.lib import config, providers

CRASH_ERRORS = ["reaped", "orphaned process", "terminated", "timeout", "no summary"]
MAX_RESUME_COUNT = 1
MAX_RESUME_PER_TICK = 1
logger = logging.getLogger(__name__)


def resume_crashed(slots: int, active: list[Spawn]) -> int:
    active_agent_ids = {s.agent_id for s in active}

    crashed = spawn.fetch(
        status="done",
        mode=SpawnMode.SOVEREIGN,
        has_session=True,
        errors=CRASH_ERRORS,
        limit=slots * 2,
    )

    crashed = [s for s in crashed if s.agent_id not in active_agent_ids]
    crashed = [s for s in crashed if s.resume_count < MAX_RESUME_COUNT]

    cfg = config.load()
    agent_map = agents.batch_get([s.agent_id for s in crashed])
    if cfg.swarm.agents:
        crashed = [
            s for s in crashed if (a := agent_map.get(s.agent_id)) and a.handle in cfg.swarm.agents
        ]
    if cfg.swarm.providers:
        allowed = set(cfg.swarm.providers)
        crashed = [
            s
            for s in crashed
            if (a := agent_map.get(s.agent_id))
            and a.model
            and providers.models.map(a.model) in allowed
        ]
    crashed = [
        s
        for s in crashed
        if (a := agent_map.get(s.agent_id))
        and a.model
        and not providers.router.provider_blocked(providers.models.map(a.model))
    ]

    resumed = 0
    limit = min(slots, MAX_RESUME_PER_TICK)
    for s in crashed[:limit]:
        agent = agents.get(s.agent_id)
        if not agent or not agent.model or agent.archived_at:
            continue
        try:
            spawn.increment_resume_count(s.id)
            instruction = (
                'you exited without sleeping. no human is here. continue working or `space sleep "summary"`.'
                if s.error == "no summary"
                else None
            )
            result = spawn.launch(agent_id=agent.id, spawn=s, instruction=instruction)
            spawn.write_daemon_event(result.id, "resuming")
            logger.info(
                "crash_resume spawn_id=%s agent=%s error=%s",
                s.id[:8],
                agent.handle,
                s.error,
            )
            resumed += 1
        except Exception:
            logger.exception("crash_resume:%s", s.id[:8])
    return resumed
