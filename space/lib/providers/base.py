import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from space.lib.providers.types import ProviderEvent

logger = logging.getLogger(__name__)

MAX_JSONL_LINE_CHARS = 500
TAIL_CHUNK_SIZE = 8192


def normalize_event(
    event_type: str,
    content: Any,
    agent: str,
    timestamp: str | None,
) -> ProviderEvent:
    return {
        "type": event_type,
        "content": content,
        "agent": agent,
        "timestamp": timestamp,
    }  # type: ignore[return-value]


def stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and any(
        isinstance(c, dict) and c.get("type") == "image" for c in content
    ):
        return "[Image content]"
    return json.dumps(content, default=str)


def iter_jsonl(path: Path, *, label: str) -> Iterator[dict[str, Any]]:
    try:
        with Path(path).open() as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "%s: invalid JSONL in %s: %r (%s)",
                        label,
                        path,
                        line[:MAX_JSONL_LINE_CHARS],
                        e,
                    )
                    continue
                if isinstance(event, dict):
                    yield event
                else:
                    logger.warning("%s: non-object JSONL in %s: %r", label, path, event)
    except OSError as e:
        logger.warning("%s: failed to read %s (%s)", label, path, e)


def iter_jsonl_tail(path: Path, *, label: str, max_lines: int = 50) -> Iterator[dict[str, Any]]:
    try:
        file_size = path.stat().st_size
        if file_size == 0:
            return

        with path.open("rb") as f:
            chunk_size = min(TAIL_CHUNK_SIZE, file_size)
            seek_pos = file_size - chunk_size
            f.seek(seek_pos)
            data = f.read(chunk_size).decode("utf-8", errors="replace")

            lines = data.split("\n")
            if seek_pos > 0 and lines:
                lines = lines[1:]

            count = 0
            for line in reversed(lines):
                if count >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        yield event
                        count += 1
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning("%s: failed to read tail %s (%s)", label, path, e)
