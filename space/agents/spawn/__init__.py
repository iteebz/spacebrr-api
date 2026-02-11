"""Spawn primitives: process execution and lifecycle."""

from .launch import launch, write_daemon_event
from .lifecycle import (
    clear_process,
    done,
    get_checklist,
    reap,
    reconcile,
    set_pid,
    stop,
    terminate,
)
from .log import LogEntry, log
from .repo import (
    clear_inertia_summaries,
    count,
    create,
    fetch,
    get,
    get_or_create,
    increment_resume_count,
    touch,
    update,
)
from .trace import (
    AUTO_SUMMARY_PREFIX,
    EventsPage,
    SpawnStats,
    events_file_path,
    extract_last_cwd,
    extract_last_response,
    format_event,
    has_work_events,
    read_events,
    stats,
    stream_all_active,
    stream_live,
    was_resumed,
)
from .usage import usage


def __getattr__(name: str):
    if name == "cli":
        from . import cli as _cli  # noqa: PLC0415

        return _cli
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AUTO_SUMMARY_PREFIX",
    "EventsPage",
    "LogEntry",
    "SpawnStats",
    "clear_inertia_summaries",
    "clear_process",
    "count",
    "create",
    "done",
    "events_file_path",
    "extract_last_cwd",
    "extract_last_response",
    "fetch",
    "format_event",
    "get",
    "get_checklist",
    "get_or_create",
    "has_work_events",
    "increment_resume_count",
    "launch",
    "log",
    "read_events",
    "reap",
    "reconcile",
    "set_pid",
    "stats",
    "stop",
    "stream_all_active",
    "stream_live",
    "terminate",
    "touch",
    "update",
    "usage",
    "was_resumed",
    "write_daemon_event",
]
