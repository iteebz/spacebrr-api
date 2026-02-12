
from datetime import UTC, datetime

from space.lib import config, state

LAST_SKIP_KEY = "daemon_last_skip"


def is_on() -> bool:
    return config.load().swarm.enabled


def on(
    limit: int | None = None,
    concurrency: int | None = None,
    agents_list: list[str] | None = None,
    providers_list: list[str] | None = None,
    *,
    project: str | None = None,
    reset_filters: bool = False,
    reset_agents: bool = False,
    reset_providers: bool = False,
    reset_project: bool = False,
    restart_daemon: bool = False,
) -> bool:
    cfg = config.load()
    was_off = not cfg.swarm.enabled
    cfg.swarm.enabled = True
    if was_off:
        cfg.swarm.enabled_at = datetime.now(UTC).isoformat()
    if limit is not None:
        cfg.swarm.limit = limit
        if not cfg.swarm.enabled_at:
            cfg.swarm.enabled_at = datetime.now(UTC).isoformat()
    if concurrency is not None:
        cfg.swarm.concurrency = concurrency
    clear_agents = reset_filters or reset_agents
    clear_providers = reset_filters or reset_providers
    clear_project = reset_filters or reset_project
    if agents_list is not None:
        cfg.swarm.agents = agents_list
    elif clear_agents:
        cfg.swarm.agents = None
    if providers_list is not None:
        cfg.swarm.providers = providers_list
    elif clear_providers:
        cfg.swarm.providers = None
    if project is not None:
        cfg.swarm.project = project
    elif clear_project:
        cfg.swarm.project = None
    config.save(cfg)
    if restart_daemon:
        from space.agents.daemon.lifecycle import restart  # noqa: PLC0415

        restart()
    else:
        ensure()
    return was_off


def off() -> bool:
    from space.agents.daemon.lifecycle import stop  # noqa: PLC0415

    was_on = is_on()
    cfg = config.load()
    cfg.swarm.enabled = False
    cfg.swarm.limit = None
    config.save(cfg)
    stop()
    return was_on


def ensure() -> int | None:
    from space.agents.daemon.lifecycle import pid, start  # noqa: PLC0415

    if existing := pid():
        return existing
    return start() if is_on() else None


def limit_reached(completed_count: int) -> bool:
    cfg = config.load()
    if cfg.swarm.limit is None:
        return False
    return completed_count >= cfg.swarm.limit


def enabled_at() -> str | None:
    return config.load().swarm.enabled_at


def last_skip() -> str | None:
    return state.get(LAST_SKIP_KEY)


def status() -> dict[str, object]:
    from space.agents.daemon.lifecycle import pid  # noqa: PLC0415

    daemon_pid = pid()
    return {
        "running": daemon_pid is not None,
        "pid": daemon_pid,
        "enabled": is_on(),
        "enabled_at": enabled_at(),
        "last_skip": last_skip(),
    }
