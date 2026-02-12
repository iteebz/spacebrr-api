
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_cache: dict[str, tuple[Any, datetime]] = {}
_lock = threading.Lock()

DEFAULT_TTL_SECONDS = 300


def get(key: str) -> Any | None:
    with _lock:
        if key not in _cache:
            return None
        value, expires = _cache[key]
        if datetime.now(UTC) > expires:
            del _cache[key]
            return None
        return value


def set(key: str, value: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    with _lock:
        _cache[key] = (value, expires)
        # Periodic cleanup to prevent unbound growth
        if len(_cache) % 100 == 0:
            now = datetime.now(UTC)
            keys = [k for k, (_, exp) in _cache.items() if now > exp]
            for k in keys:
                del _cache[k]


def delete(key: str) -> None:
    with _lock:
        _cache.pop(key, None)


def clear() -> None:
    with _lock:
        _cache.clear()


def cached(prefix: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = f"{prefix}:{args}:{sorted(kwargs.items())}"
            result = get(key)
            if result is not None:
                return result
            result = fn(*args, **kwargs)
            set(key, result, ttl_seconds)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def memoize(ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = f"{fn.__module__}.{fn.__name__}:{args}:{sorted(kwargs.items())}"
            result = get(key)
            if result is not None:
                return result
            result = fn(*args, **kwargs)
            set(key, result, ttl_seconds)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
