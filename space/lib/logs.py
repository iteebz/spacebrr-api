"""Unified logging for daemon, API, and client processes."""

import json
import logging
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from space.lib import paths

MAX_CLIENT_ENTRIES = 100
DEFAULT_LOG_LINES = 100
logger = logging.getLogger(__name__)


def _get_max_lines() -> int:
    config_path = paths.dot_space() / "config.yaml"
    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text()) or {}
            return config.get("logs", {}).get("max_lines", DEFAULT_LOG_LINES)
        except Exception as e:
            logger.warning("Failed to read log config at %s: %s", config_path, e)
    return DEFAULT_LOG_LINES


client_logger = logging.getLogger("space.client")


def _path(name: str) -> Path:
    p = paths.dot_space() / "logs" / f"{name}.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _truncate(path: Path, max_lines: int | None = None) -> None:
    if max_lines is None:
        max_lines = _get_max_lines()
    if not path.exists():
        return
    lines = path.read_text().splitlines()
    if len(lines) > max_lines:
        path.write_text("\n".join(lines[-max_lines:]) + "\n")


def _json_line(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), default=str)


def reset(name: str) -> None:
    p = _path(name)
    line = _json_line({"ts": datetime.now(UTC).isoformat(), "level": "INFO", "msg": "reset"})
    p.write_text(line + "\n")


def write(name: str, exc: BaseException, context: str = "") -> None:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "level": "ERROR",
        "msg": context or type(exc).__name__,
        "error": str(exc),
        "traceback": tb,
    }
    p = _path(name)
    with p.open("a") as f:
        f.write(_json_line(entry) + "\n")
    _truncate(p)


def client(entries: list[dict[str, Any]], log_name: str = "app") -> dict[str, Any]:
    lines = []
    for entry in entries[:MAX_CLIENT_ENTRIES]:
        level = entry.get("level", "info").upper()
        log_entry: dict[str, Any] = {
            "ts": entry.get("timestamp", datetime.now(UTC).isoformat()),
            "level": level,
            "msg": entry.get("message", ""),
        }
        if context := entry.get("context"):
            log_entry.update(context)
        client_logger.log(getattr(logging, level, logging.INFO), log_entry.get("msg"))
        lines.append(_json_line(log_entry))

    p = _path(log_name)
    with p.open("a") as f:
        f.write("\n".join(lines) + "\n")
    _truncate(p)

    return {"ok": True, "processed": min(len(entries), MAX_CLIENT_ENTRIES)}


def clear(name: str) -> dict[str, Any]:
    p = _path(name)
    if p.exists():
        p.write_text("")
    return {"ok": True}


def info(name: str, msg: str, **context: Any) -> None:
    entry: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "level": "INFO",
        "msg": msg,
    }
    if context:
        entry.update(context)
    p = _path(name)
    with p.open("a") as f:
        f.write(_json_line(entry) + "\n")
    _truncate(p)
