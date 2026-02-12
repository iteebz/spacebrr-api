
import logging
import re
import time
from datetime import UTC, datetime, timedelta

from space.core.models import Agent
from space.lib import config, state

from . import limits
from .models import map as model_to_provider
from .types import ProviderName

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
COOLDOWN_STATE_KEY = "provider_retry_cooldowns"
NOTIFIED_STATE_KEY = "provider_quota_notified"
_QUOTA_RESET_RE = re.compile(
    r"quota exhausted\s*\(resets\s*(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?\.?\)",
    re.IGNORECASE,
)

_capacity_cache: dict[ProviderName, tuple[bool, float]] = {}


def _cooldowns() -> dict[str, float]:
    data = state.get(COOLDOWN_STATE_KEY, {})
    return data if isinstance(data, dict) else {}


def _set_cooldowns(data: dict[str, float]) -> None:
    state.set(COOLDOWN_STATE_KEY, data)


def _notified() -> set[str]:
    data = state.get(NOTIFIED_STATE_KEY, set())
    return data if isinstance(data, set) else set()


def _set_notified(data: set[str]) -> None:
    state.set(NOTIFIED_STATE_KEY, data)


def _purge_expired(data: dict[str, float], now_ts: float) -> dict[str, float]:
    return {k: v for k, v in data.items() if v > now_ts}


def _cooldown_active(provider: ProviderName) -> bool:
    now_ts = datetime.now(UTC).timestamp()
    data = _cooldowns()
    pruned = _purge_expired(data, now_ts)
    if pruned != data:
        _set_cooldowns(pruned)
        notified = _notified()
        expired_providers = set(data.keys()) - set(pruned.keys())
        if expired_providers:
            _set_notified(notified - expired_providers)
    expiry = pruned.get(provider)
    return isinstance(expiry, (int, float)) and expiry > now_ts


def provider_blocked(provider: ProviderName) -> bool:
    return _cooldown_active(provider)


def provider_blocked_until(provider: ProviderName) -> datetime | None:
    now_ts = datetime.now(UTC).timestamp()
    data = _cooldowns()
    pruned = _purge_expired(data, now_ts)
    if pruned != data:
        _set_cooldowns(pruned)
    expiry = pruned.get(provider)
    if not isinstance(expiry, (int, float)):
        return None
    return datetime.fromtimestamp(expiry, UTC)


def block_provider_for(provider: ProviderName, *, seconds: int) -> datetime:
    now = datetime.now(UTC)
    until = now + timedelta(seconds=max(1, seconds))
    data = _purge_expired(_cooldowns(), now.timestamp())
    data[provider] = until.timestamp()
    _set_cooldowns(data)
    clear_cache()
    return until


def block_provider_from_error(provider: ProviderName, error: str) -> datetime | None:
    m = _QUOTA_RESET_RE.search(error)
    if not m:
        return None
    hours, minutes, seconds = (int(p or "0") for p in m.groups())
    ttl_seconds = (hours * 3600) + (minutes * 60) + seconds
    if ttl_seconds <= 0:
        return None
    return block_provider_for(provider, seconds=ttl_seconds)


def _has_capacity(provider: ProviderName) -> bool:
    if _cooldown_active(provider):
        return False
    now = time.monotonic()
    cached = _capacity_cache.get(provider)
    if cached and (now - cached[1]) < CACHE_TTL_SECONDS:
        return cached[0]

    result = _check_provider(provider)
    _capacity_cache[provider] = (result, now)
    return result


def provider_available(provider: ProviderName) -> bool:
    return _has_capacity(provider)


def _check_provider(provider: ProviderName) -> bool:
    try:
        checkers = {"claude": limits.claude, "codex": limits.codex}
        checker = checkers.get(provider)
        if not checker:
            return True

        data = checker()
        if data.error or not data.buckets:
            return True

        threshold = config.load().swarm.capacity_threshold
        return all(b.remaining_pct >= threshold for b in data.buckets)
    except Exception:
        logger.debug("Capacity check failed for %s, assuming available", provider)
        return True


def resolve(agent: Agent) -> str | None:
    if not agent.model:
        return None

    provider = model_to_provider(agent.model)
    if _has_capacity(provider):
        return agent.model

    logger.warning("%s at capacity, skipping %s", provider, agent.handle)
    return None


def clear_cache() -> None:
    _capacity_cache.clear()


def needs_notification(provider: ProviderName) -> bool:
    notified = _notified()
    return provider not in notified


def mark_notified(provider: ProviderName) -> None:
    _set_notified(_notified() | {provider})


def record_provider_error(provider: ProviderName, error: str) -> datetime | None:
    blocked_until = block_provider_from_error(provider, error)
    if blocked_until:
        logger.warning(
            "quota failure for %s, blocked retries until %s",
            provider,
            blocked_until.isoformat(),
        )
        return blocked_until
    if "quota" in error.lower():
        clear_cache()
        logger.warning("quota failure for %s, invalidated router cache", provider)
    return None
