import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from space.core.models import Agent

MINUTE = 60
HOUR = 3600
DAY = 86400
WEEK = 604800
MONTH = 2592000
YEAR = 31536000

_UNITS = [(YEAR, "y"), (MONTH, "mo"), (WEEK, "w"), (DAY, "d"), (HOUR, "h"), (MINUTE, "m")]


def age_seconds(seconds: int | float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 10:
        return "now"
    for threshold, label in _UNITS:
        if seconds >= threshold:
            return f"{int(seconds / threshold)}{label}"
    return f"{int(seconds)}s"


def ago(timestamp_str: str | None) -> str:
    if not timestamp_str:
        return "-"
    try:
        timestamp = datetime.fromisoformat(str(timestamp_str))
    except (ValueError, TypeError):
        return "-"

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    now = datetime.now(UTC)
    diff = now - timestamp
    return age_seconds(diff.total_seconds())


def duration(t1: str | datetime, t2: str | datetime | None = None) -> str:
    def to_dt(t: str | datetime) -> datetime:
        if isinstance(t, str):
            dt = datetime.fromisoformat(t)
        else:
            dt = t
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt

    dt1 = to_dt(t1)
    dt2 = to_dt(t2) if t2 else datetime.now(UTC)
    seconds = abs((dt2 - dt1).total_seconds())
    return format_duration(seconds)


def format_duration(seconds: float) -> str:
    if seconds < MINUTE:
        return f"{int(seconds)}s"
    if seconds < HOUR:
        return f"{int(seconds / MINUTE)}m"
    if seconds < DAY:
        hours = int(seconds / HOUR)
        mins = int((seconds % HOUR) / MINUTE)
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    days = int(seconds / DAY)
    hours = int((seconds % DAY) / HOUR)
    return f"{days}d {hours}h" if hours else f"{days}d"


def parse_duration(spec: str) -> timedelta:
    spec = (spec or "").strip().lower()
    if not spec:
        raise ValueError("duration required")

    pattern = r"^(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$"
    match = re.match(pattern, spec)
    if not match or not any(match.groups()):
        raise ValueError(f"invalid duration: {spec}")

    weeks, days, hours, minutes = (int(g or 0) for g in match.groups())
    return timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes)


def agent_name(agent: Agent | None, fallback: str = "unknown") -> str:
    if not agent:
        return fallback
    suffix = "(human)" if agent.type == "human" else "(ai)"
    return f"{agent.handle}{suffix}"


def pct(
    value: float | None,
    *,
    null: str = "·",
    suffix: str = "",
    color: Callable[[str], str] | None = None,
) -> str:
    fmt: Callable[[str], str] = color or (lambda s: s)
    if value is None:
        return fmt(f"  {null}{' ' * len(suffix) if suffix else ''}")
    return fmt(f"{value:>3.0f}{suffix}")


def truncate(text: str, length: int = 70, suffix: str = "...", *, flatten: bool = False) -> str:
    if flatten:
        text = text.replace("\n", " ").strip()
    if len(text) <= length:
        return text
    return text[: length - len(suffix)] + suffix
