"""Agent selection and spawning."""

import logging
import random
from datetime import UTC, datetime

from space import agents
from space.agents import daemon, spawn
from space.core.models import Agent, Spawn, SpawnMode
from space.core.types import AgentId
from space.ledger import insights
from space.lib import config, providers, state, store
from space.lib.providers.types import ProviderName

logger = logging.getLogger(__name__)

INBOX_WEIGHT = 1.5
RECENT_SPAWN_PENALTY = 0.5
FAILURE_BACKOFF_SECONDS = 300


def _notify_quota_block(provider: ProviderName, until: datetime) -> None:
    try:
        from space.agents import defaults  # noqa: PLC0415
        from space.ledger import insights, projects  # noqa: PLC0415

        system = defaults.ensure_system()
        duration = until - datetime.now(UTC)
        hours, remainder = divmod(int(duration.total_seconds()), 3600)
        minutes = remainder // 60
        time_str = f"{hours}h{minutes}m" if hours else f"{minutes}m"

        insights.create(
            project_id=projects.GLOBAL_PROJECT_ID,
            agent_id=system.id,
            content=f"{provider} quota exhausted, blocked for {time_str}",
            domain="quota",
        )
        providers.router.mark_notified(provider)
    except Exception:
        logger.exception("Failed to create quota notification insight")


def pick_idle_agents(count: int, active: list[Spawn]) -> list[Agent]:
    if count <= 0:
        return []
    eligible = eligible_agents()
    if not eligible:
        return []

    active_ids = {s.agent_id for s in active}
    failed_ids = _recently_failed_agents()
    last_agent = _last_finished_agent()
    idle = [
        a
        for a in eligible
        if a.id not in active_ids and a.id not in failed_ids and a.id != last_agent
    ]

    from space.ledger import projects  # noqa: PLC0415

    cfg = config.load()
    project_id = projects.get_scope(cfg.swarm.project) if cfg.swarm.project else None
    with_inbox = insights.agents_with_inbox(project_id)
    has_stream = insights.has_unprocessed_stream()
    spawn_counts = _recent_spawn_counts([a.id for a in idle])
    last_spawned = _last_spawned([a.id for a in idle])
    max_spawns = max(spawn_counts.values()) if spawn_counts else 1

    def agent_weight(a: Agent) -> float:
        n = spawn_counts.get(a.id, 0)
        fairness_base = 1 + (max_spawns - n) / (max_spawns + 1)
        fairness = fairness_base**2

        inbox_mult = INBOX_WEIGHT if a.handle in with_inbox else 1
        stream_mult = INBOX_WEIGHT if has_stream else 1

        last = last_spawned.get(a.id)
        recent_penalty = 1.0
        if last:
            delta = (datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds()
            if delta < 300:
                recent_penalty = RECENT_SPAWN_PENALTY

        cfg_weights = config.load().swarm.weights or {}
        bias = cfg_weights.get(a.handle, 1.0)
        return fairness * inbox_mult * stream_mult * recent_penalty * bias

    selected: list[Agent] = []
    remaining = [(a, agent_weight(a)) for a in idle]

    while len(selected) < count and remaining:
        weights = [w for _, w in remaining]
        if sum(weights) == 0:
            break
        [(pick, _)] = random.choices(remaining, weights=weights, k=1)  # noqa: S311
        remaining = [(a, w) for a, w in remaining if a.id != pick.id]
        selected.append(pick)

    return selected[:count]


def _recent_spawn_counts(agent_ids: list[str]) -> dict[str, int]:
    if not agent_ids:
        return {}
    with store.ensure() as conn:
        cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        placeholders = ",".join("?" * len(agent_ids))
        rows = conn.execute(
            f"SELECT agent_id, COUNT(*) as cnt FROM spawns WHERE agent_id IN ({placeholders}) AND created_at >= ? GROUP BY agent_id",  # noqa: S608
            [*agent_ids, cutoff],
        ).fetchall()
        return {row["agent_id"]: row["cnt"] for row in rows}


def _last_spawned(agent_ids: list[str]) -> dict[str, str | None]:
    if not agent_ids:
        return {}
    with store.ensure() as conn:
        placeholders = ",".join("?" * len(agent_ids))
        rows = conn.execute(
            f"SELECT agent_id, MAX(created_at) as last FROM spawns WHERE agent_id IN ({placeholders}) GROUP BY agent_id",  # noqa: S608
            agent_ids,
        ).fetchall()
        return {row["agent_id"]: row["last"] for row in rows}


def _last_finished_agent() -> str | None:
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT agent_id FROM spawns WHERE status = 'done' ORDER BY last_active_at DESC LIMIT 1"
        ).fetchone()
        return row["agent_id"] if row else None


def available_slots(active: list[Spawn]) -> int:
    cfg = config.load()
    return max(0, cfg.swarm.concurrency - len(active))


def eligible_agents() -> list[Agent]:
    cfg = config.load()
    all_agents = agents.fetch(type="ai")
    eligible = [a for a in all_agents if a.model and not a.archived_at]
    if cfg.swarm.agents:
        eligible = [a for a in eligible if a.handle in cfg.swarm.agents]
    if cfg.swarm.providers:
        allowed = set(cfg.swarm.providers)
        eligible = [a for a in eligible if providers.models.map(a.model or "") in allowed]
    return [
        a
        for a in eligible
        if providers.router.provider_available(providers.models.map(a.model or ""))
    ]


def active_sovereign() -> list[Spawn]:
    """Fetch only sovereign spawns with status active."""

    return spawn.fetch(status="active", mode=SpawnMode.SOVEREIGN)


def _recently_failed_agents() -> set[AgentId]:
    failures = state.get("agent_failures", {})
    if not isinstance(failures, dict):
        return set()
    cutoff = datetime.now(UTC).timestamp() - FAILURE_BACKOFF_SECONDS
    return {AgentId(aid) for aid, ts in failures.items() if ts > cutoff}


def _record_agent_failure(agent_id: AgentId, error: str) -> None:
    failures = state.get("agent_failures", {})
    if not isinstance(failures, dict):
        failures = {}
    failures[agent_id] = datetime.now(UTC).timestamp()
    state.set("agent_failures", failures)
    logger.warning("recorded failure for %s: %s", agent_id, error[:100])


def _clear_agent_failure(agent_id: AgentId) -> None:
    failures = state.get("agent_failures", {})
    if isinstance(failures, dict) and agent_id in failures:
        del failures[agent_id]
        state.set("agent_failures", failures)


BASE_SKILLS = ["wake", "connect", "manual"]


def _resolve_skills(agent: Agent) -> list[str]:
    base = list(BASE_SKILLS)
    if not agent.identity:
        return base
    try:
        identity = agents.identity.load(agent.identity)
        if identity.skills:
            seen = set(base)
            for s in identity.skills:
                if s not in seen:
                    base.append(s)
                    seen.add(s)
    except Exception:
        logger.debug("Failed to load identity %s skills", agent.identity)
    return base


def spawn_agent(agent: Agent) -> None:
    model = providers.router.resolve(agent)
    if not model:
        if agent.model:
            provider = providers.models.map(agent.model)
            if providers.router.provider_blocked(provider):
                blocked_until = providers.router.provider_blocked_until(provider)
                until = blocked_until.isoformat() if blocked_until else "unknown"
                logger.warning("skip %s: %s cooldown until %s", agent.handle, provider, until)
            else:
                logger.warning("skip %s: %s at capacity", agent.handle, provider)
        else:
            logger.warning("skip %s: no model configured", agent.handle)
        state.set(daemon.LAST_SKIP_KEY, datetime.now(UTC).isoformat())
        return
    try:
        spawn.launch(
            agent_id=agent.id,
            skills=_resolve_skills(agent),
            write_starting_event=True,
        )
        _clear_agent_failure(agent.id)
    except Exception as exc:
        _record_agent_failure(agent.id, str(exc))
        if agent.model:
            provider = providers.models.map(agent.model)
            blocked_until = providers.router.record_provider_error(provider, str(exc))
            if blocked_until and providers.router.needs_notification(provider):
                _notify_quota_block(provider, blocked_until)
        raise
