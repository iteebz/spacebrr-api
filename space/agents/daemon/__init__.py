"""Daemon: autonomous agent spawning loop."""

from space.agents.daemon import cli, lifecycle, resume, scheduler, swarm, sync, tick
from space.agents.daemon.lifecycle import pid, run, start, stop
from space.agents.daemon.resume import CRASH_ERRORS, resume_crashed
from space.agents.daemon.scheduler import (
    active_sovereign,
    available_slots,
    pick_idle_agents,
    spawn_agent,
)
from space.agents.daemon.swarm import (
    LAST_SKIP_KEY,
    enabled_at,
    ensure,
    is_on,
    last_skip,
    limit_reached,
    off,
    on,
    status,
)
from space.agents.daemon.sync import check_email_sync

__all__ = [
    "CRASH_ERRORS",
    "LAST_SKIP_KEY",
    "active_sovereign",
    "available_slots",
    "check_email_sync",
    "cli",
    "enabled_at",
    "ensure",
    "is_on",
    "last_skip",
    "lifecycle",
    "limit_reached",
    "off",
    "on",
    "pick_idle_agents",
    "pid",
    "resume",
    "resume_crashed",
    "run",
    "scheduler",
    "spawn_agent",
    "start",
    "status",
    "stop",
    "swarm",
    "sync",
    "tick",
]
