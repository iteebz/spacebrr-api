from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypedDict

if TYPE_CHECKING:
    from space.lib import tools

ProviderName = Literal["claude", "codex", "gemini"]


class TextEvent(TypedDict):
    type: Literal["text"]
    content: str
    agent: str
    timestamp: str | None


class ToolCallContent(TypedDict):
    tool_name: str
    input: dict[str, Any]
    tool_use_id: str


class ToolCallEvent(TypedDict):
    type: Literal["tool_call"]
    content: ToolCallContent
    agent: str
    timestamp: str | None


class ToolResultContent(TypedDict):
    output: str
    is_error: bool
    tool_use_id: str


class ToolResultEvent(TypedDict):
    type: Literal["tool_result"]
    content: ToolResultContent
    agent: str
    timestamp: str | None


class ContextInitContent(TypedDict):
    context_case: str | None
    context: str | None


class ContextInitEvent(TypedDict):
    type: Literal["context_init"]
    content: ContextInitContent
    agent: str
    timestamp: str | None


class StateChangeContent(TypedDict):
    resource: str | None
    action: str | None
    delta: dict[str, Any]


class StateChangeEvent(TypedDict):
    type: Literal["state_change"]
    content: StateChangeContent
    agent: str
    timestamp: str | None


class UsageContent(TypedDict):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    model: str


class UsageEvent(TypedDict):
    type: Literal["usage"]
    content: UsageContent
    agent: str
    timestamp: str | None


ProviderEvent = (
    TextEvent | ToolCallEvent | ToolResultEvent | ContextInitEvent | StateChangeEvent | UsageEvent
)


@dataclass
class UsageStats:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    model: str


class Provider(Protocol):
    @staticmethod
    def normalize_event(
        event: dict[str, Any], identity: str, tool_map: dict[str, str] | None = None
    ) -> list[ProviderEvent]: ...

    @staticmethod
    def launch_args() -> list[str]: ...

    @staticmethod
    def task_launch_args() -> list[str]: ...

    @staticmethod
    def build_command(
        model: str,
        session_id: str | None,
        context: str | None,
        root_dir: str,
        cwd: str | None = None,
        allowed_tools: set[tools.Tool] | None = None,
        images: list[str] | None = None,
    ) -> tuple[list[str], str | None]: ...

    @staticmethod
    def parse_usage(events_file: Path) -> UsageStats: ...

    @staticmethod
    def context_limit(model: str) -> int: ...

    @staticmethod
    def input_tokens_from_event(event: dict[str, Any]) -> int: ...
