from pathlib import Path
from typing import Any

from space.lib import tools
from space.lib.providers.types import ProviderEvent, UsageStats
from space.lib.tools import allowed_for, normalize_tool_name

from . import base


def launch_args(
    allowed_tools: set[tools.Tool] | None = None, has_prompt: bool = False
) -> list[str]:
    tool_list = allowed_for("gemini", allowed_tools)
    args = ["--allowed-tools", ",".join(tool_list)]
    if has_prompt:
        args.append("--prompt-interactive")
    return args


def task_launch_args(allowed_tools: set[tools.Tool] | None = None) -> list[str]:
    tool_list = allowed_for("gemini", allowed_tools)
    return ["--yolo", "--allowed-tools", ",".join(tool_list)]


def build_command(
    model: str,
    session_id: str | None,
    context: str | None,
    root_dir: str,
    cwd: str | None = None,
    allowed_tools: set[tools.Tool] | None = None,
    images: list[str] | None = None,
) -> tuple[list[str], str | None]:
    args = ["gemini", "--output-format", "stream-json"]
    args += launch_args(allowed_tools)
    args += ["--model", model]
    args += ["--include-directories", cwd or root_dir]
    if session_id:
        args += ["--resume", session_id]
    if context:
        args.append(context)
    return args, None


def normalize_event(
    event: dict[str, Any], identity: str, tool_map: dict[str, str] | None = None
) -> list[ProviderEvent]:
    msg_type = event.get("type")
    timestamp = event.get("timestamp")

    if tool_map is None:
        tool_map = {}

    if msg_type == "message":
        role = event.get("role")
        content = event.get("content", "")
        if role == "assistant" and content:
            return [base.normalize_event("text", content, identity, timestamp)]

    elif msg_type == "tool_use":
        tool_id = event.get("tool_id", "")
        tool_name = event.get("tool_name", "")
        params = event.get("parameters", {})

        normalized_name = normalize_tool_name("gemini", tool_name)
        if tool_id and normalized_name:
            tool_map[tool_id] = normalized_name

        return [
            base.normalize_event(
                "tool_call",
                {
                    "tool_name": normalized_name,
                    "input": params,
                    "tool_use_id": tool_id,
                },
                identity,
                timestamp,
            )
        ]

    elif msg_type == "tool_result":
        tool_id = event.get("tool_id", "")
        status = event.get("status", "")
        output = event.get("output", "")

        if not output and "error" in event:
            output = str(event["error"])

        is_error = status == "error"

        return [
            base.normalize_event(
                "tool_result",
                {
                    "output": output,
                    "is_error": is_error,
                    "tool_use_id": tool_id,
                },
                identity,
                timestamp,
            )
        ]

    elif msg_type == "result":
        stats = event.get("stats")
        if isinstance(stats, dict):
            return [
                base.normalize_event(
                    "usage",
                    {
                        "input_tokens": int(stats.get("input_tokens", 0)),
                        "output_tokens": int(stats.get("output_tokens", 0)),
                        "cache_read_tokens": 0,
                        "cache_creation_tokens": 0,
                        "model": event.get("model", ""),
                    },
                    identity,
                    timestamp,
                )
            ]

    return []


_SYSTEM_OVERHEAD = 10000
_PER_TURN_OVERHEAD = 2000
_CHARS_PER_TOKEN = 4


def _estimate_tokens(events_file: Path) -> tuple[int, int, str]:
    content_chars = 0
    turns = 0
    output_chars = 0
    model = "unknown"

    for event in base.iter_jsonl(events_file, label="gemini.estimate"):
        if model == "unknown" and event.get("model"):
            model = event["model"]
        msg_type = event.get("type")
        if msg_type == "message" and event.get("role") == "assistant":
            turns += 1
            c = event.get("content", "")
            if isinstance(c, str):
                content_chars += len(c)
                output_chars += len(c)
        elif msg_type == "tool_result":
            c = event.get("output", "")
            if isinstance(c, str):
                content_chars += len(c)
        elif msg_type == "tool_use":
            params = event.get("parameters", {})
            content_chars += len(str(params))

    input_est = content_chars // _CHARS_PER_TOKEN + _SYSTEM_OVERHEAD + turns * _PER_TURN_OVERHEAD
    output_est = output_chars // _CHARS_PER_TOKEN
    return input_est, output_est, model


def parse_usage(events_file: Path) -> UsageStats:
    """Parse usage from tail, falling back to estimation for active spawn."""
    model = "unknown"
    stats = {}

    for event in base.iter_jsonl_tail(events_file, label="gemini.parse_usage", max_lines=20):
        if (not model or model == "unknown") and event.get("model"):
            model = event["model"]
        if event.get("type") == "result" and "stats" in event and not stats:
            stats = event["stats"]
        if stats and model != "unknown":
            break

    if stats:
        return UsageStats(
            stats.get("input_tokens", 0),
            stats.get("output_tokens", 0),
            0,
            0,
            model,
        )

    input_est, output_est, est_model = _estimate_tokens(events_file)
    if input_est > _SYSTEM_OVERHEAD:
        return UsageStats(
            input_est,
            output_est,
            0,
            0,
            est_model if model == "unknown" else model,
        )

    return UsageStats(0, 0, 0, 0, model)


def input_tokens_from_event(event: dict[str, Any]) -> int:
    if event.get("type") == "result":
        stats = event.get("stats")
        if isinstance(stats, dict):
            for key in (
                "input_tokens",
                "input",
                "prompt_tokens",
                "promptTokenCount",
                "inputTokenCount",
            ):
                if key in stats:
                    return int(stats.get(key, 0))
            total = int(stats.get("total_tokens", 0))
            output = int(stats.get("output_tokens", 0))
            if total > 0 and output >= 0:
                return max(0, total - output)

    message = event.get("message")
    if isinstance(message, dict):
        usage = message.get("usage") or message.get("usage_metadata")
        if isinstance(usage, dict):
            for key in (
                "input_tokens",
                "prompt_tokens",
                "promptTokenCount",
                "inputTokenCount",
                "total_input_tokens",
            ):
                if key in usage:
                    return int(usage.get(key, 0))

    return 0
