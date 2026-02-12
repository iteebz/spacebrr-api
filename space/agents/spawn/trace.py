import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from space import agents
from space.core.models import Agent, Spawn, SpawnStatus
from space.core.types import SpawnId
from space.lib import providers, pubsub, store
from space.lib.parser import extract_cd
from space.lib.providers import ProviderName

from .events import find_events_file, iter_normalized
from .repo import fetch, get

logger = logging.getLogger(__name__)

_events: pubsub.Registry[dict[str, Any]] = pubsub.Registry()
subscribe = _events.subscribe
unsubscribe = _events.unsubscribe
publish = _events.publish
clear = _events.clear

WRITE_ACTIONS = {"add", "propose", "submit", "send", "edit", "create", "archive", "done"}
READ_ACTIONS = {"list", "show", "info", "search"}


@dataclass
class EventsPage:
    events: list[dict[str, Any]]
    total: int
    has_more: bool


@dataclass
class SpawnContext:
    spawn: Spawn
    agent: Agent
    provider: ProviderName | None
    events_file: Path | None


def spawn_duration(spawn: Spawn) -> float | None:
    if not spawn.created_at or not spawn.last_active_at:
        return None
    start = datetime.fromisoformat(spawn.created_at)
    end = datetime.fromisoformat(spawn.last_active_at)
    return (end - start).total_seconds()


VERB_MAP = {
    "Bash": "run",
    "Read": "read",
    "LS": "listed",
    "Glob": "globbed",
    "Grep": "searched",
    "Edit": "edited",
    "MultiEdit": "edited",
    "Write": "wrote",
    "WebFetch": "fetched",
    "WebSearch": "searched",
    "TodoWrite": "planned",
}


def format_event(event: dict[str, Any]) -> str | None:
    t = event.get("type")
    content = event.get("content", {})

    if t == "text":
        text = content if isinstance(content, str) else ""
        if len(text) > 80:
            text = text[:77] + "..."
        return f"  {text}" if text.strip() else None

    if t == "tool_call":
        tool = str(content.get("tool_name") or "?")
        verb = VERB_MAP.get(tool) or tool.lower()
        inp = content.get("input", {})

        if tool == "Bash":
            cmd = inp.get("command", "")[:60]
            return f"run {cmd}"
        if tool in ("Read", "Edit", "MultiEdit", "Write"):
            path = inp.get("file_path", inp.get("path", ""))
            return f"{verb} {path.split('/')[-1]}"
        if tool in ("Grep", "WebSearch"):
            pat = inp.get("pattern", inp.get("query", ""))[:40]
            return f"{verb} {pat}"
        if tool == "WebFetch":
            url = inp.get("url", "")
            prompt = inp.get("prompt", "")[:40]
            return f"{verb} {url} ({prompt})" if prompt else f"{verb} {url}"
        if tool == "TodoWrite":
            todos = inp.get("todos", [])
            return f"{verb} {len(todos)} items"
        path = str(inp.get("file_path") or inp.get("path") or inp.get("command") or "")
        label = path.split("/")[-1] if path else ""
        return f"{verb} {label}" if label else verb

    if t == "tool_result":
        if content.get("is_error"):
            return f"  error: {content.get('output', '')[:60]}"
        return None

    return None


@dataclass
class PrimitiveStats:
    read: int = 0
    write: int = 0


@dataclass
class TraceAnalysis:
    primitives: dict[str, PrimitiveStats] = field(default_factory=dict)
    commands: int = 0


@dataclass
class SpawnStats:
    decisions: int = 0
    insights: int = 0
    tasks_created: int = 0
    tasks_completed: int = 0
    files_edited: int = 0
    duration_seconds: float | None = None


def analyze(spawn_id: str) -> TraceAnalysis:
    events_file = find_events_file(spawn_id)
    if not events_file or not events_file.exists():
        return TraceAnalysis()

    primitives: dict[str, PrimitiveStats] = {}
    commands = 0

    with events_file.open() as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") != "item.completed":
                continue

            item = event.get("item", {})
            if item.get("type") != "command_execution":
                continue

            cmd = item.get("command", "")
            commands += 1

            m = re.search(
                r"space\s+(decision|insight|task|spawn|agent)\s+(\w+)",
                cmd,
            )
            if not m:
                continue

            prim, action = m.groups()
            if prim not in primitives:
                primitives[prim] = PrimitiveStats()

            if action in WRITE_ACTIONS:
                primitives[prim].write += 1
            elif action in READ_ACTIONS:
                primitives[prim].read += 1

    return TraceAnalysis(primitives=primitives, commands=commands)


def stats(spawn_id: str) -> SpawnStats:
    s = get(SpawnId(spawn_id))
    ctx = _resolve_context(s)

    with store.ensure() as conn:
        decisions = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE spawn_id = ?", (spawn_id,)
        ).fetchone()[0]
        insights = conn.execute(
            "SELECT COUNT(*) FROM insights WHERE spawn_id = ?", (spawn_id,)
        ).fetchone()[0]
        tasks_created = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE spawn_id = ?", (spawn_id,)
        ).fetchone()[0]
        tasks_completed = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE spawn_id = ? AND status = 'done'",
            (spawn_id,),
        ).fetchone()[0]

    files_edited = sum(
        1
        for event in _iter_normalized_events(ctx)
        if event.get("type") == "tool_call"
        and event.get("content", {}).get("tool_name") in ("Edit", "MultiEdit", "Write")
    )

    return SpawnStats(
        decisions=decisions,
        insights=insights,
        tasks_created=tasks_created,
        tasks_completed=tasks_completed,
        files_edited=files_edited,
        duration_seconds=spawn_duration(s),
    )


AUTO_SUMMARY_PREFIX = "[auto] "
AUTO_SUMMARY_MAX_LENGTH = 200


def has_work_events(spawn_id: str) -> bool:
    s = get(SpawnId(spawn_id))
    ctx = _resolve_context(s)
    if not ctx.events_file or not ctx.provider:
        return False
    for event in _iter_normalized_events(ctx):
        if event.get("type") in {"tool_use", "assistant"}:
            return True
    return False


def extract_last_response(spawn_id: str) -> str | None:
    s = get(SpawnId(spawn_id))
    ctx = _resolve_context(s)
    if not ctx.events_file or not ctx.provider:
        return None

    last_text: str | None = None
    for event in _iter_normalized_events(ctx):
        if event.get("type") == "text":
            content = event.get("content", "")
            if isinstance(content, str) and content.strip():
                last_text = content.strip()

    if not last_text:
        return None
    if len(last_text) > AUTO_SUMMARY_MAX_LENGTH:
        last_text = last_text[: AUTO_SUMMARY_MAX_LENGTH - 3] + "..."
    return f"{AUTO_SUMMARY_PREFIX}{last_text}"


def extract_last_cwd(spawn_id: str) -> str | None:
    s = get(SpawnId(spawn_id))
    ctx = _resolve_context(s)
    if not ctx.events_file or not ctx.provider:
        return None

    last_cwd: str | None = None
    for event in _iter_normalized_events(ctx):
        if event.get("type") != "tool_call":
            continue
        content = event.get("content", {})
        if not isinstance(content, dict):
            continue
        if str(content.get("tool_name")) != "Bash":
            continue
        inp = content.get("input", {})
        cmd = inp.get("command", "") if isinstance(inp, dict) else ""
        cd_path = extract_cd(cmd)
        if cd_path:
            last_cwd = cd_path

    return last_cwd


def events_file_path(spawn_id: str) -> Path | None:
    return find_events_file(spawn_id)


def was_resumed(spawn_id: str) -> bool | None:
    """Check if spawn was resumed from an existing session.

    Returns True if resumed, False if fresh, None if unknown.
    """
    events_file = find_events_file(spawn_id)
    if not events_file or not events_file.exists():
        return None

    with events_file.open() as f:
        for line in f:
            try:
                event = json.loads(line)
                if event.get("type") == "context_init":
                    return event.get("context_case") == "RESUME"
            except json.JSONDecodeError:
                continue
    return None


def _resolve_context(spawn: Spawn) -> SpawnContext:
    agent = agents.get(spawn.agent_id)
    provider = providers.map(agent.model) if agent.model else None
    events_file = find_events_file(spawn.id)
    return SpawnContext(spawn=spawn, agent=agent, provider=provider, events_file=events_file)


def _iter_normalized_events(
    ctx: SpawnContext,
    tool_map: dict[str, str] | None = None,
):
    if not ctx.events_file:
        return
    yield from iter_normalized(ctx.events_file, ctx.agent.handle, tool_map)


def read_events(spawn_id: str, offset: int = 0, limit: int = 100) -> EventsPage:
    s = get(SpawnId(spawn_id))
    ctx = _resolve_context(s)

    if not ctx.events_file or not ctx.provider:
        return EventsPage(events=[], total=0, has_more=False)

    try:
        all_events = list(_iter_normalized_events(ctx))
    except Exception as e:
        logger.error(f"Failed to read events file: {e}")
        return EventsPage(events=[], total=0, has_more=False)

    total = len(all_events)
    page = all_events[offset : offset + limit]
    has_more = offset + limit < total

    return EventsPage(events=page, total=total, has_more=has_more)


async def stream_live(
    spawn: Spawn, *, heartbeat_interval: float = 1.0
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream events from spawn by polling trace file for new lines.

    File-based polling enables cross-process streaming: the CLI can watch
    events from spawns started by daemon or other processes.
    """
    full_id = spawn.id
    ctx = _resolve_context(spawn)
    initial_cwd = extract_last_cwd(full_id)

    yield {
        "type": "context",
        "spawn_id": spawn.id[:8],
        "handle": ctx.agent.handle,
        "status": spawn.status,
        "created_at": spawn.created_at,
        "cwd": initial_cwd,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    provider_cls = providers.get_provider(ctx.provider) if ctx.provider else None
    tool_map: dict[str, str] = {}
    file_pos = 0

    if ctx.events_file and ctx.events_file.exists():
        try:
            with ctx.events_file.open() as f:
                while True:
                    line = f.readline()
                    if not line:
                        file_pos = f.tell()
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if event.get("type") == "human_input":
                            yield event
                        elif provider_cls:
                            for normalized in provider_cls.normalize_event(
                                event, ctx.agent.handle, tool_map
                            ):
                                yield normalized
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to replay events: {e}")

    if spawn.status != SpawnStatus.ACTIVE:
        status_val = spawn.status.value if hasattr(spawn.status, "value") else spawn.status
        yield {
            "type": "summary",
            "status": status_val,
            "duration_seconds": spawn_duration(spawn),
            "last_active_at": spawn.last_active_at,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        return

    try:
        while True:
            await asyncio.sleep(heartbeat_interval)

            current_spawn = get(full_id)
            if current_spawn.status != SpawnStatus.ACTIVE:
                status_val = (
                    current_spawn.status.value
                    if hasattr(current_spawn.status, "value")
                    else current_spawn.status
                )
                yield {
                    "type": "summary",
                    "status": status_val,
                    "duration_seconds": spawn_duration(current_spawn),
                    "last_active_at": current_spawn.last_active_at,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                return

            if not ctx.events_file or not ctx.events_file.exists():
                continue

            with ctx.events_file.open() as f:
                f.seek(file_pos)
                while True:
                    line = f.readline()
                    if not line:
                        file_pos = f.tell()
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if event.get("type") == "human_input":
                            yield event
                        elif provider_cls:
                            for normalized in provider_cls.normalize_event(
                                event, ctx.agent.handle, tool_map
                            ):
                                yield normalized
                    except json.JSONDecodeError:
                        continue

    except (asyncio.CancelledError, GeneratorExit):
        return


async def stream_all_active(*, poll_interval: float = 2.0) -> AsyncGenerator[dict[str, Any], None]:
    tracked: dict[str, tuple[asyncio.Task[None], asyncio.Queue[dict[str, Any]]]] = {}
    merge_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    spawn_cwd: dict[str, str] = {}

    def _check_cd(event: dict[str, Any], spawn_id: str) -> None:
        if event.get("type") != "tool_call":
            return
        content = event.get("content", {})
        if not isinstance(content, dict):
            return
        if str(content.get("tool_name")) != "Bash":
            return
        inp = content.get("input", {})
        cmd = inp.get("command", "") if isinstance(inp, dict) else ""
        cd_path = extract_cd(cmd)
        if cd_path:
            spawn_cwd[spawn_id] = cd_path

    async def _forward(spawn: Spawn, queue: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            async for event in stream_live(spawn):
                event["_spawn_id"] = spawn.id
                _check_cd(event, spawn.id)
                await queue.put(event)
        except asyncio.CancelledError:
            pass

    def _sync_active():
        active = fetch(status=SpawnStatus.ACTIVE)
        active_ids = {s.id for s in active}
        current_ids = set(tracked.keys())

        added = []
        for s in active:
            if s.id not in current_ids:
                q = merge_queue
                task = asyncio.create_task(_forward(s, q))
                tracked[s.id] = (task, q)
                agent = agents.get(s.agent_id)
                try:
                    last_cwd = extract_last_cwd(s.id)
                except Exception:
                    last_cwd = None
                if last_cwd:
                    spawn_cwd[s.id] = last_cwd
                added.append(
                    {
                        "spawn_id": s.id,
                        "handle": agent.handle if agent else s.id[:8],
                        "cwd": spawn_cwd.get(s.id),
                    }
                )

        removed = []
        for sid in current_ids - active_ids:
            task, _ = tracked.pop(sid)
            task.cancel()
            removed.append(sid)

        return added, removed

    last_emitted_cwd: dict[str, str | None] = {}

    try:
        added, _ = _sync_active()
        for a in added:
            yield {
                "type": "spawn_attached",
                "spawn_id": a["spawn_id"],
                "handle": a["handle"],
                "cwd": a.get("cwd"),
                "timestamp": datetime.now(UTC).isoformat(),
            }

        if not tracked:
            yield {
                "type": "status",
                "status": "idle",
                "message": "No active spawns",
                "timestamp": datetime.now(UTC).isoformat(),
            }

        while True:
            try:
                event = await asyncio.wait_for(merge_queue.get(), timeout=poll_interval)
                yield event
                sid = event.get("_spawn_id")
                if sid and spawn_cwd.get(sid) != last_emitted_cwd.get(sid):
                    cwd = spawn_cwd[sid]
                    last_emitted_cwd[sid] = cwd
                    yield {
                        "type": "spawn_cwd",
                        "spawn_id": sid,
                        "cwd": cwd,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
            except TimeoutError:
                added, removed = _sync_active()
                for sid in removed:
                    spawn_cwd.pop(sid, None)
                    last_emitted_cwd.pop(sid, None)
                    yield {
                        "type": "spawn_detached",
                        "spawn_id": sid,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                for a in added:
                    yield {
                        "type": "spawn_attached",
                        "spawn_id": a["spawn_id"],
                        "handle": a["handle"],
                        "cwd": a.get("cwd"),
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                yield {"type": "keepalive", "timestamp": datetime.now(UTC).isoformat()}

    except (asyncio.CancelledError, GeneratorExit):
        return
    finally:
        for task, _ in tracked.values():
            task.cancel()
        tracked.clear()
