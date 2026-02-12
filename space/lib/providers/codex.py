from pathlib import Path
from typing import Any

from space.lib import tools
from space.lib.providers.types import ProviderEvent, UsageStats

from . import base


def launch_args() -> list[str]:
    """Return launch arguments for headless Codex execution."""
    return ["--json", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"]


task_launch_args = launch_args


def build_command(
    model: str,
    session_id: str | None,
    context: str | None,
    root_dir: str,
    cwd: str | None = None,
    allowed_tools: set[tools.Tool] | None = None,
    images: list[str] | None = None,
) -> tuple[list[str], str | None]:
    """Build Codex CLI launch command."""
    args = ["codex", "exec", *launch_args(), "--model", model]
    # Keep Codex workspace-root behavior aligned with other providers.
    args += ["--cd", cwd or root_dir]
    if session_id:
        args += ["resume", session_id, "-"]
    else:
        args += ["-"]
    return args, context


def normalize_event(
    event: dict[str, Any], identity: str, tool_map: dict[str, str] | None = None
) -> list[ProviderEvent]:
    timestamp = event.get("timestamp")
    event_type = event.get("type")
    item = event.get("item", {})
    item_type = item.get("type")

    if tool_map is None:
        tool_map = {}

    if event_type == "item.started" and item_type == "command_execution":
        item_id = item.get("id", "")
        command = item.get("command", "")
        tool_map[item_id] = "Bash"

        normalized_command = command
        if command.startswith("/bin/zsh -lc '") and command.endswith("'"):
            normalized_command = command[14:-1]

        return [
            base.normalize_event(
                "tool_call",
                {
                    "tool_name": "Bash",
                    "input": {"command": normalized_command},
                    "tool_use_id": item_id,
                },
                identity,
                timestamp,
            )
        ]

    if event_type == "item.completed" and item_type == "command_execution":
        item_id = item.get("id", "")
        output = item.get("aggregated_output", "")
        exit_code = item.get("exit_code", 0)
        is_error = exit_code != 0

        return [
            base.normalize_event(
                "tool_result",
                {
                    "output": output,
                    "is_error": is_error,
                    "tool_use_id": item_id,
                },
                identity,
                timestamp,
            )
        ]

    if event_type == "item.completed" and item_type == "reasoning":
        text = item.get("text", "")
        if text:
            return [base.normalize_event("text", text, identity, timestamp)]

    if event_type == "item.completed" and item_type == "agent_message":
        text = item.get("text", "")
        if text:
            return [base.normalize_event("text", text, identity, timestamp)]

    if event_type == "item.completed" and item_type == "file_change":
        changes = item.get("changes", [])
        if changes:
            paths = [c.get("path", "") for c in changes]
            kinds = [c.get("kind", "update") for c in changes]
            summary = ", ".join(
                f"{k} {p.split('/')[-1]}" for k, p in zip(kinds, paths, strict=False)
            )
            return [
                base.normalize_event(
                    "tool_result",
                    {"output": summary, "is_error": False, "tool_use_id": item.get("id", "")},
                    identity,
                    timestamp,
                )
            ]

    if event_type == "turn.completed":
        usage = event.get("usage")
        if isinstance(usage, dict):
            return [
                base.normalize_event(
                    "usage",
                    {
                        "input_tokens": int(usage.get("input_tokens", 0)),
                        "output_tokens": int(usage.get("output_tokens", 0)),
                        "cache_read_tokens": int(usage.get("cached_input_tokens", 0)),
                        "cache_creation_tokens": 0,
                        "model": event.get("model", ""),
                    },
                    identity,
                    timestamp,
                )
            ]

    return []


def parse_usage(events_file: Path) -> UsageStats:
    """Parse usage from tail of file. Only needs last turn.completed event."""
    model = "unknown"
    usage = {}

    for event in base.iter_jsonl_tail(events_file, label="codex.parse_usage", max_lines=20):
        if (not model or model == "unknown") and event.get("model"):
            model = event["model"]
        if event.get("type") == "turn.completed" and "usage" in event and not usage:
            usage = event["usage"]
        if usage and model != "unknown":
            break

    return UsageStats(
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("cached_input_tokens", 0),
        0,
        model,
    )


def input_tokens_from_event(event: dict[str, Any]) -> int:
    if event.get("type") != "turn.completed":
        return 0
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return 0
    # Codex reports cached_input_tokens as a subset of input_tokens.
    return int(usage.get("input_tokens", 0))
