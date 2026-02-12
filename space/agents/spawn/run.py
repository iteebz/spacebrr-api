
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from space.core.models import SpawnStatus
from space.core.types import SpawnId
from space.lib import providers
from space.lib.providers.types import ProviderName

from . import repo

logger = logging.getLogger(__name__)

SESSION_CAPTURE_EVENTS = {
    ("system", "init"): "session_id",
    ("init", None): "session_id",
    ("thread.started", None): "thread_id",
}
TOUCH_EVENTS = frozenset({"tool_use", "assistant"})

STDERR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ModelNotFoundError:.*", re.IGNORECASE), "model not found"),
    (
        re.compile(r"TerminalQuotaError:.*?reset after (\S+)", re.IGNORECASE),
        r"quota exhausted (resets \1)",
    ),
    (
        re.compile(r"You have exhausted your capacity.*?reset after (\S+)"),
        r"quota exhausted (resets \1)",
    ),
    (re.compile(r"rate.?limit", re.IGNORECASE), "rate limited"),
    (re.compile(r"No conversation found"), "session not found"),
    (re.compile(r"AuthenticationError|401|403.*forbidden", re.IGNORECASE), "auth failed"),
    (re.compile(r"overloaded|529|503.*unavailable", re.IGNORECASE), "provider overloaded"),
]


def clean_stderr(stderr: str) -> str:
    for pat, replacement in STDERR_PATTERNS:
        m = pat.search(stderr)
        if m:
            try:
                return m.expand(replacement)
            except (re.error, IndexError):
                return replacement
    lines = [s.strip() for s in stderr.strip().splitlines() if s.strip()]
    for line in reversed(lines):
        if line.startswith(("Error", "error", "fatal")):
            return line[:120]
    return lines[-1][:120] if lines else "unknown error"


@dataclass(slots=True)
class Result:
    returncode: int
    stderr: str


class SessionExpiredError(RuntimeError):
    pass


def _record_quota_error(provider: str, error: str) -> None:
    if provider in {"claude", "codex", "gemini"}:
        prov = cast(ProviderName, provider)
        blocked_until = providers.router.record_provider_error(prov, error)
        if blocked_until and providers.router.needs_notification(prov):
            _notify_quota_block(prov, blocked_until)


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


def handle_exit(result: Result, spawn_id: SpawnId, provider: str, session_id: str | None) -> None:
    if session_id:
        s = repo.get(spawn_id)
        if s and s.session_id != session_id:
            repo.update(s.id, session_id=session_id)

    if result.returncode == 0:
        s = repo.get(spawn_id)
        if s and s.status == SpawnStatus.ACTIVE:
            repo.update(s.id, status=SpawnStatus.DONE, error="")
        return

    s = repo.get(spawn_id)

    if s and s.session_id and result.stderr and "No conversation found" in result.stderr:
        repo.update(s.id, session_id="")
        error_msg = f"{provider.title()} spawn resume failed: session not found"
        _record_quota_error(provider, error_msg)
        raise SessionExpiredError(error_msg)

    if s and s.session_id:
        from . import trace  # noqa: PLC0415

        has_work = trace.has_work_events(spawn_id)
        if has_work:
            repo.update(s.id, status=SpawnStatus.DONE, error="")
            return

        if result.returncode == 143:
            error = f"killed (exit {result.returncode})"
        elif result.stderr:
            error = clean_stderr(result.stderr)
        else:
            error = None
        if s.error:
            error = s.error
        error = error or "no work done"
        repo.update(s.id, status=SpawnStatus.DONE, error=error)
        error_msg = f"{provider.title()} spawn {spawn_id[:8]} failed: {error}"
        _record_quota_error(provider, error_msg)
        raise RuntimeError(error_msg)

    error = clean_stderr(result.stderr)
    error_msg = f"{provider.title()} spawn failed: {error}"
    _record_quota_error(provider, error_msg)
    raise RuntimeError(error_msg)
