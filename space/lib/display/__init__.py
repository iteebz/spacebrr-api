from collections.abc import Callable

from . import ansi
from .writer import Writer as Writer
from .writer import std as std
from .writer import test as test

IDENTITY_WIDTH = 10


def format_identity(identity: str) -> str:
    escape = ansi.agent_color(identity)
    return f"{ansi.DEFAULT.bold}{escape}{identity[:IDENTITY_WIDTH]:<{IDENTITY_WIDTH}}{ansi.DEFAULT.reset}"


def format_pct(
    pct: float | None,
    *,
    null: str = "·",
    suffix: str = "",
    color: Callable[[str], str] | None = None,
) -> str:
    fmt = color or ansi.gray
    if pct is None:
        return fmt(f"  {null}{' ' * len(suffix) if suffix else ''}")
    return fmt(f"{pct:>3.0f}{suffix}")


def format_legend(identities: set[str]) -> str:
    parts = []
    for ident in sorted(identities):
        color = ansi.agent_color(ident)
        parts.append(
            f"{color}●{ansi.DEFAULT.reset} {ansi.DEFAULT.bold}{color}{ident}{ansi.DEFAULT.reset}"
        )
    return "  ".join(parts)


def format_nameplate(identity: str, pct: float | None = None) -> str:
    escape = ansi.agent_color(identity)
    at_name = f"{ansi.DEFAULT.bold}{escape}@{identity[:IDENTITY_WIDTH]}{ansi.DEFAULT.reset}"
    if pct is None:
        return f"{at_name}"
    return f"{at_name} {ansi.sky(f'{pct:.0f}%')} {ansi.gray('·')}"
