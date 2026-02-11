"""Ephemeral runtime state: ~/.space/state.yaml"""

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from space.lib import paths

_mem: dict[str, Any] | None = None
_mem_mtime: float = 0.0


def _state_path() -> Path:
    return paths.dot_space() / "state.yaml"


def _lock_path() -> Path:
    return paths.dot_space() / ".state.lock"


@contextmanager
def _locked():
    lock = _lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _load() -> dict[str, Any]:
    global _mem, _mem_mtime
    p = _state_path()
    if not p.exists():
        _mem = {}
        _mem_mtime = 0.0
        return _mem
    try:
        mtime = p.stat().st_mtime
    except OSError:
        if _mem is not None:
            return _mem
        _mem = {}
        return _mem
    if _mem is not None and mtime == _mem_mtime:
        return _mem
    try:
        _mem = yaml.safe_load(p.read_text()) or {}
        _mem_mtime = mtime
    except (yaml.YAMLError, OSError):
        if _mem is None:
            _mem = {}
    return _mem or {}


def _save(data: dict[str, Any]) -> None:
    global _mem, _mem_mtime
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, default_flow_style=False))
    _mem = data
    try:
        _mem_mtime = p.stat().st_mtime
    except OSError:
        _mem_mtime = 0.0


def get(key: str, default: Any = None) -> Any:
    with _locked():
        return _load().get(key, default)


def set(key: str, value: Any) -> None:
    with _locked():
        data = _load()
        data[key] = value
        _save(data)


def delete(key: str) -> None:
    with _locked():
        data = _load()
        data.pop(key, None)
        _save(data)


def clear() -> None:
    global _mem, _mem_mtime
    with _locked():
        p = _state_path()
        if p.exists():
            p.unlink()
        _mem = None
        _mem_mtime = 0.0
