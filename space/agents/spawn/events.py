import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from space.lib import paths, providers
from space.lib.providers import ProviderName


def find_events_file(spawn_id: str) -> Path | None:
    spawns_dir = paths.dot_space() / "spawns"
    if not spawns_dir.exists():
        return None
    for provider_dir in spawns_dir.iterdir():
        if provider_dir.is_dir():
            p = provider_dir / f"{spawn_id}.jsonl"
            if p.exists():
                return p
    old_path = spawns_dir / f"{spawn_id}.jsonl"
    if old_path.exists():
        return old_path
    return None


def resolve_provider(path: Path) -> ProviderName | None:
    name = path.parent.name
    return name if name in providers.PROVIDER_NAMES else None


def input_tokens(raw: dict[str, object], provider: str | None) -> int:
    provider_cls = (
        providers.get_provider(provider) if provider in providers.PROVIDER_NAMES else None
    )
    if provider_cls and hasattr(provider_cls, "input_tokens_from_event"):
        try:
            inp = int(provider_cls.input_tokens_from_event(raw))
            if inp > 0:
                return inp
        except Exception:  # noqa: S110
            pass

    msg = raw.get("message")
    if isinstance(msg, dict):
        usage = msg.get("usage")
        if isinstance(usage, dict):
            return (
                int(usage.get("input_tokens", 0))
                + int(usage.get("cache_read_input_tokens", 0))
                + int(usage.get("cache_creation_input_tokens", 0))
            )

    if raw.get("type") == "turn.completed":
        usage = raw.get("usage")
        if isinstance(usage, dict):
            if provider == "codex":
                return int(usage.get("input_tokens", 0))
            return int(usage.get("input_tokens", 0)) + int(usage.get("cached_input_tokens", 0))

    if raw.get("type") == "result":
        stats = raw.get("stats")
        if isinstance(stats, dict):
            return int(stats.get("input_tokens", 0))

    return 0


_EST_CHARS_PER_TOKEN = 4
_EST_SYSTEM_OVERHEAD = 10000
_EST_PER_TURN_OVERHEAD = 2000


def estimate_ctx_pct(
    cumulative_chars: int,
    turns: int,
    model: str | None,
    provider_name: str,
) -> float | None:
    if cumulative_chars <= 0:
        return None
    est_tokens = (
        cumulative_chars // _EST_CHARS_PER_TOKEN
        + _EST_SYSTEM_OVERHEAD
        + turns * _EST_PER_TURN_OVERHEAD
    )
    ctx_limit = (
        providers.models.context_limit(model or "")
        if provider_name in providers.PROVIDER_NAMES
        else 200000
    )
    return max(0.0, 100 - est_tokens / ctx_limit * 100)


def iter_normalized(
    path: Path,
    identity: str,
    tool_map: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    provider = resolve_provider(path)
    provider_cls = providers.get_provider(provider) if provider else None
    if tool_map is None:
        tool_map = {}
    with path.open() as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                if raw.get("type") == "human_input":
                    yield raw
                elif provider_cls:
                    yield from provider_cls.normalize_event(raw, identity, tool_map)
                else:
                    yield raw
            except json.JSONDecodeError:
                continue
