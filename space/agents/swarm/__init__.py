from datetime import date
from typing import Any, Literal, overload

from .commands import main
from .dash import payload as _dash_payload
from .dash import render as _dash_render
from .tail import (
    StreamState,
    estimate_ctx_pct,
    generate_tail,
    input_tokens_from_event,
    read_stream,
    replay_date,
    save_tail,
    spawn_path,
    spawn_path_by_id,
    tail_dir,
    tail_path,
    tail_spawns,
)


@overload
def dash(frame: int | None = ..., *, json: Literal[False] = ...) -> list[str]: ...
@overload
def dash(frame: int | None = ..., *, json: Literal[True]) -> dict[str, Any]: ...


def dash(frame: int | None = None, *, json: bool = False) -> list[str] | dict[str, Any]:
    if json:
        return _dash_payload()
    return _dash_render(frame=frame)


@overload
def tail(target_date: date, *, save: Literal[False] = ...) -> list[str]: ...
@overload
def tail(target_date: date, *, save: Literal[True]) -> dict[str, int | str]: ...


def tail(target_date: date, *, save: bool = False) -> list[str] | dict[str, int | str]:
    if save:
        return save_tail(target_date)
    return generate_tail(target_date)


__all__ = [
    "StreamState",
    "dash",
    "estimate_ctx_pct",
    "input_tokens_from_event",
    "main",
    "read_stream",
    "replay_date",
    "spawn_path",
    "spawn_path_by_id",
    "tail",
    "tail_dir",
    "tail_path",
    "tail_spawns",
]
