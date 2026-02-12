import inspect
import logging
import sys
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, NoReturn

from space.core.errors import NotFoundError, ReferenceError, SpaceError, ValidationError

logger = logging.getLogger(__name__)

_SENSITIVE_ARG_NAMES = {
    "body",
    "body_file",
    "content",
    "context",
    "message",
    "prompt",
    "result",
    "summary",
    "text",
}


def _json_safe(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v[:50]]
    if isinstance(v, dict):
        out: dict[str, Any] = {}
        for k, x in list(v.items())[:50]:
            out[str(k)] = _json_safe(x)
        return out
    return f"<{type(v).__name__}>"


def _safe_telemetry_args(
    sig: inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any] | None:
    try:
        bound = sig.bind_partial(*args, **kwargs)
    except Exception:
        return None

    out: dict[str, Any] = {}
    for k, v in bound.arguments.items():
        if k in ("cli_ctx", "ctx"):
            continue
        if k in _SENSITIVE_ARG_NAMES:
            if v is None:
                out[k] = None
            elif isinstance(v, str):
                out[k] = {"redacted": True, "len": len(v)}
            else:
                out[k] = {"redacted": True, "type": type(v).__name__}
            continue
        out[k] = _json_safe(v)

    return out or None


def _capture_telemetry(usage: str, args: dict[str, Any] | None, exit_code: int, duration_ms: int):
    try:
        from space.lib import telemetry

        telemetry.capture(command=usage, args=args, exit_code=exit_code, duration_ms=duration_ms)
    except Exception as e:
        logger.debug(f"telemetry capture failed: {e}")


def _wrap_handler(usage: str, f: Callable[..., Any]) -> Callable[..., Any]:
    sig = inspect.signature(f)

    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any):
        start = time.monotonic()
        exit_code = 0

        try:
            return f(*args, **kwargs)
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 1
            raise
        except (ValidationError, NotFoundError, ReferenceError) as e:
            logger.error(f"{usage}: {e}")
            sys.stderr.write(f"{e}\n")
            exit_code = 1
            sys.exit(1)
        except SpaceError as e:
            logger.error(f"{usage}: {e}")
            sys.stderr.write(f"{e}\n")
            exit_code = 1
            sys.exit(1)
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            telemetry_args = _safe_telemetry_args(sig, args, kwargs)
            _capture_telemetry(usage, telemetry_args, exit_code, duration_ms)

    return wrapper


def space_cmd(usage: str):

    def decorator[F: Callable[..., Any]](f: F) -> F:
        return _wrap_handler(usage, f)  # type: ignore[return-value]

    return decorator


def echo(msg: str = "", err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    stream.write(msg + "\n")


def fail(msg: str, code: int = 1) -> NoReturn:
    sys.stderr.write(msg + "\n")
    sys.exit(code)
