import base64
import json
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from space.lib import paths, tools
from space.lib.providers.types import ProviderEvent, UsageStats
from space.lib.tools import disallowed_for

from . import base


def launch_args(allowed_tools: set[tools.Tool] | None = None) -> list[str]:
    disallowed = disallowed_for("claude", allowed_tools)
    args = ["--dangerously-skip-permissions"]
    if disallowed:
        args += ["--disallowedTools", ",".join(disallowed)]
    return args


def task_launch_args(allowed_tools: set[tools.Tool] | None = None) -> list[str]:
    disallowed = disallowed_for("claude", allowed_tools)
    args = ["--print", "--dangerously-skip-permissions"]
    if disallowed:
        args += ["--disallowedTools", ",".join(disallowed)]
    return args


def _images_to_base64(image_filenames: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    uploads_dir = paths.dot_space() / "images" / "uploads"
    images_dir = paths.dot_space() / "images"

    for filename in image_filenames:
        filepath = None
        for base_dir in (uploads_dir, images_dir):
            candidate = base_dir / filename
            if candidate.exists():
                filepath = candidate
                break

        if not filepath:
            continue

        media_type = mimetypes.guess_type(str(filepath))[0] or "image/png"
        data = base64.b64encode(filepath.read_bytes()).decode("utf-8")
        blocks.append(
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
        )

    return blocks


def build_command(
    model: str,
    session_id: str | None,
    context: str | None,
    root_dir: str,
    cwd: str | None = None,
    allowed_tools: set[tools.Tool] | None = None,
    images: list[str] | None = None,
) -> tuple[list[str], str | None]:
    args = ["claude", "--print", "--output-format", "stream-json", "--verbose"]
    args += launch_args(allowed_tools)
    args += ["--model", model]
    if cwd:
        args += ["--add-dir", cwd]
    if session_id:
        args += ["--resume", session_id]

    if images:
        args += ["--input-format", "stream-json"]
        content: list[dict[str, Any]] = _images_to_base64(images)
        if context:
            content.append({"type": "text", "text": context})
        message = {"type": "user", "message": {"role": "user", "content": content}}
        return args, json.dumps(message)

    return args, context


def _usage_event(msg: dict[str, Any], identity: str, timestamp: str | None) -> ProviderEvent | None:
    usage = msg.get("usage")
    if not isinstance(usage, dict) or not usage.get("input_tokens"):
        return None
    input_tokens = (
        int(usage.get("input_tokens", 0))
        + int(usage.get("cache_read_input_tokens", 0))
        + int(usage.get("cache_creation_input_tokens", 0))
    )
    return base.normalize_event(
        "usage",
        {
            "input_tokens": input_tokens,
            "output_tokens": int(usage.get("output_tokens", 0)),
            "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0)),
            "cache_creation_tokens": int(usage.get("cache_creation_input_tokens", 0)),
            "model": msg.get("model", ""),
        },
        identity,
        timestamp,
    )


def normalize_event(
    event: dict[str, Any], identity: str, tool_map: dict[str, str] | None = None
) -> list[ProviderEvent]:
    event_type = event.get("type")
    timestamp = event.get("timestamp") or datetime.now(UTC).isoformat()

    if tool_map is None:
        tool_map = {}

    if event_type == "context_init":
        return [
            base.normalize_event(
                "context_init",
                {
                    "context_case": event.get("context_case"),
                    "context": event.get("context"),
                },
                identity,
                timestamp,
            )
        ]

    if event_type == "state_change":
        return [
            base.normalize_event(
                "state_change",
                {
                    "resource": event.get("resource"),
                    "action": event.get("action"),
                    "delta": event.get("delta", {}),
                },
                identity,
                timestamp,
            )
        ]

    if event_type == "assistant":
        msg = event.get("message", {})
        content_blocks = msg.get("content", [])
        if not isinstance(content_blocks, list):
            return []

        out: list[ProviderEvent] = []
        usage_ev = _usage_event(msg, identity, timestamp)
        if usage_ev:
            out.append(usage_ev)

        for block in content_blocks:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text", "")
                if text:
                    out.append(base.normalize_event("text", text, identity, timestamp))
                    return out

            elif block_type == "tool_use":
                tool_use_id = block.get("id", "")
                tool_name = block.get("name", "")
                if tool_use_id and tool_name:
                    tool_map[tool_use_id] = tool_name
                out.append(
                    base.normalize_event(
                        "tool_call",
                        {
                            "tool_name": tool_name,
                            "input": block.get("input", {}),
                            "tool_use_id": tool_use_id,
                        },
                        identity,
                        timestamp,
                    )
                )
                return out

        return out

    if event_type == "user":
        msg = event.get("message", {})
        content = msg.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    tool_use_id = item.get("tool_use_id", "")
                    tool_name = tool_map.get(tool_use_id, "")

                    raw_content = item.get("content", "")
                    output = base.stringify_content(raw_content)
                    if tool_name == "Read":
                        line_count = output.count("\n")
                        if line_count > 0:
                            output = f"({line_count} lines)"

                    return [
                        base.normalize_event(
                            "tool_result",
                            {
                                "output": output,
                                "is_error": item.get("is_error", False),
                                "tool_use_id": tool_use_id,
                            },
                            identity,
                            timestamp,
                        )
                    ]
    return []


def parse_usage(events_file: Path) -> UsageStats:
    model = "unknown"
    last_usage = {}

    for event in base.iter_jsonl_tail(events_file, label="claude.parse_usage", max_lines=20):
        msg = event.get("message", {})
        if isinstance(msg, dict):
            if (not model or model == "unknown") and msg.get("model"):
                model = msg["model"]
            if "usage" in msg and not last_usage:
                last_usage = msg["usage"]
        if last_usage and model != "unknown":
            break

    input_tokens = last_usage.get("input_tokens", 0)
    cache_read = last_usage.get("cache_read_input_tokens", 0)
    cache_creation = last_usage.get("cache_creation_input_tokens", 0)

    return UsageStats(
        input_tokens + cache_read + cache_creation,
        last_usage.get("output_tokens", 0),
        cache_read,
        cache_creation,
        model,
    )


def input_tokens_from_event(event: dict[str, Any]) -> int:
    msg = event.get("message")
    if not isinstance(msg, dict):
        return 0
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return 0
    return (
        int(usage.get("input_tokens", 0))
        + int(usage.get("cache_read_input_tokens", 0))
        + int(usage.get("cache_creation_input_tokens", 0))
    )
