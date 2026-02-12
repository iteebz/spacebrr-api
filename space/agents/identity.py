import os
from dataclasses import dataclass
from typing import Any

import yaml

from space import ctx
from space.core.errors import NotFoundError, ValidationError
from space.core.types import AgentId
from space.lib import config, tools
from space.lib.tools import parse_tools


def resolve(explicit: str | None) -> AgentId | None:
    if explicit:
        return AgentId(explicit)
    return current()


def current() -> AgentId | None:
    if val := os.environ.get("SPACE_IDENTITY"):
        return AgentId(val)

    cfg = config.load()
    if cfg.default_identity:
        return AgentId(cfg.default_identity)
    return None


@dataclass
class Identity:
    name: str
    description: str
    lens: list[str]
    tools: set[tools.Tool] | None
    skills: list[str]
    content: str


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text

    lines = text.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    frontmatter_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :]).lstrip()

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        frontmatter = {}

    return frontmatter, body


def load(name: str) -> Identity:
    path = ctx.identity_path(name)
    if not path.exists():
        raise NotFoundError(f"Identity '{name}' not found")

    try:
        text = path.read_text()
    except Exception as e:
        raise ValidationError(f"Failed to read identity: {e}") from e

    frontmatter, body = parse_frontmatter(text)

    return Identity(
        name=name.removesuffix(".md"),
        description=frontmatter.get("description", ""),
        lens=frontmatter.get("lens", []),
        tools=parse_tools(frontmatter.get("tools")),
        skills=frontmatter.get("skills", []),
        content=body,
    )


def get(name: str) -> str:
    path = ctx.identity_path(name)
    if not path.exists():
        raise NotFoundError(f"Identity '{name}' not found")
    try:
        return path.read_text()
    except Exception as e:
        raise ValidationError(f"Failed to read identity: {e}") from e


def update(name: str, content: str) -> None:
    path = ctx.identity_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(content)
        temp_path.replace(path)
    except OSError as e:
        raise ValidationError(f"Failed to write identity: {e}") from e
