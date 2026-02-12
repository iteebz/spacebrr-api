
import json
import os
import subprocess
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CLAUDE_KEYCHAIN_SERVICE = "Claude Code-credentials"
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


@dataclass
class UsageBucket:
    name: str
    used_pct: float
    remaining_pct: float
    resets_at: datetime | None


@dataclass
class ProviderLimits:
    provider: str
    buckets: list[UsageBucket]
    error: str | None = None


def _parse_reset(iso_str: str | None) -> datetime | None:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str)
    except ValueError:
        return None


def _format_delta(dt: datetime | None) -> str:
    if not dt:
        return "?"
    delta = dt - datetime.now(UTC)
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "now"
    hours, remainder = divmod(total_seconds, 3600)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h"
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def claude() -> ProviderLimits:
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                os.getenv("USER", ""),
                "-s",
                CLAUDE_KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        creds = json.loads(result.stdout.strip())
        token = creds["claudeAiOauth"]["accessToken"]
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        return ProviderLimits("claude", [], error="not authenticated")

    req = urllib.request.Request(  # noqa: S310
        CLAUDE_USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError):
        return ProviderLimits("claude", [], error="api error")

    buckets = []
    for key in ["five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"]:
        bucket = data.get(key)
        if not bucket:
            continue
        used = bucket.get("utilization", 0)
        name = key.replace("_", " ")
        if key == "five_hour":
            name = "5h"
        elif key == "seven_day":
            name = "7d"
        elif key == "seven_day_opus":
            name = "7d (opus)"
        elif key == "seven_day_sonnet":
            name = "7d (sonnet)"
        buckets.append(
            UsageBucket(
                name=name,
                used_pct=used,
                remaining_pct=100 - used,
                resets_at=_parse_reset(bucket.get("resets_at")),
            )
        )

    return ProviderLimits("claude", buckets)


def codex() -> ProviderLimits:
    limits = _codex_rate_limits()
    if limits is None:
        return ProviderLimits("codex", [], error="no live session limits found")
    return ProviderLimits("codex", limits)


def _codex_rate_limits() -> list[UsageBucket] | None:
    sessions_root = Path.home() / ".codex" / "sessions"
    if not sessions_root.exists():
        return None

    latest_file: Path | None = None
    latest_mtime = 0.0
    for path in sessions_root.rglob("*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_file = path

    if not latest_file:
        return None

    last_lines: deque[str] = deque(maxlen=200)
    try:
        with latest_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                last_lines.append(line.strip())
    except OSError:
        return None

    rate_limits = None
    for line in reversed(last_lines):
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = event.get("payload", event)
        if payload.get("type") != "token_count":
            continue
        rate_limits = payload.get("rate_limits")
        if rate_limits:
            break

    if not rate_limits:
        return None

    buckets: list[UsageBucket] = []
    for key, default_name in [("primary", "5h"), ("secondary", "7d")]:
        window = rate_limits.get(key) if isinstance(rate_limits, dict) else None
        if not window:
            continue
        used = float(window.get("used_percent", 0))
        resets_at = window.get("resets_at")
        resets_dt = datetime.fromtimestamp(resets_at, UTC) if isinstance(resets_at, int) else None
        buckets.append(
            UsageBucket(
                name=default_name,
                used_pct=used,
                remaining_pct=100 - used,
                resets_at=resets_dt,
            )
        )

    return buckets or None


def all_providers() -> list[ProviderLimits]:
    return [claude(), codex()]


def format_limits(limits: list[ProviderLimits]) -> str:
    lines: list[str] = []
    for p in limits:
        lines.append("")
        if p.error:
            lines.append(f"{p.provider}  {p.error}")
            continue
        for b in p.buckets:
            reset_str = _format_delta(b.resets_at)
            lines.append(
                f"{p.provider:6} {b.name:14} {b.remaining_pct:5.1f}% remaining  (resets in {reset_str})"
            )
    return "\n".join(lines)
