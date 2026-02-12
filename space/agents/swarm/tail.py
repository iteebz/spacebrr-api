import json
import random
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from space import agents as agents_mod
from space.agents import spawn
from space.agents.spawn import events
from space.core.models import Spawn, SpawnStatus
from space.core.types import AgentId, SpawnId
from space.lib import paths, providers, trace
from space.lib.display import ansi, format_nameplate
from space.lib.parser import extract_cd
from space.lib.providers import base as provider_base

_STALE_THRESHOLD_SECONDS = 120

_RENDER_CACHE: dict[Path, tuple[float, list[tuple[str, str]]]] = {}


def _resolve_handle(agent_id: str, cache: dict[str, str]) -> str:
    if agent_id not in cache:
        agent = agents_mod.get(AgentId(agent_id))
        cache[agent_id] = agent.handle if agent else agent_id[:8]
    return cache[agent_id]


@dataclass
class StreamState:
    spawn_id: str
    handle: str
    path: Path
    position: int = 0
    ctx_pct: float | None = None
    tool_map: dict[str, str] | None = None
    model: str | None = None
    pending_text: str = ""
    cumulative_chars: int = 0
    turns: int = 0
    has_real_usage: bool = False
    shown_starting: bool = False
    lines_read: int = 0
    cwd: str | None = None


def spawn_path(s, agent_cache: dict[str, str]) -> Path | None:
    agent = agents_mod.get(s.agent_id)
    provider = providers.map(agent.model) if agent and agent.model else "claude"
    p = paths.dot_space() / "spawns" / provider / f"{s.id}.jsonl"
    if p.exists():
        return p
    return events.find_events_file(s.id)


spawn_path_by_id = events.find_events_file
estimate_ctx_pct = events.estimate_ctx_pct
input_tokens_from_event = events.input_tokens


def _local_date(iso_ts: str | None) -> date | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo:
            dt = dt.astimezone()
        return dt.date()
    except (ValueError, TypeError):
        return None


def _format_daemon_event(ident: str, action: str, reason: str | None = None) -> str:
    normalized = (action or "").strip().lower()
    if normalized == "starting":
        status = ansi.lime("FRESH START")
        detail = ansi.gray("new spawn")
    elif normalized == "resuming":
        status = ansi.gold("RESUME")
        detail = ansi.gray("older incomplete session")
    else:
        status = ansi.gray((action or "event").upper())
        detail = ansi.gray("lifecycle")
    suffix = f" ({ansi.white(reason)})" if reason else ""
    return f"{ansi.mention('daemon')}: {status} {ansi.mention(ident)} {detail}{suffix}"


def _format_resume_event(ident: str) -> str:
    return (
        f"{ansi.mention('daemon')}: {ansi.lime('RESUMED')} {ansi.mention(ident)} "
        f"{ansi.gray('context attached')}"
    )


def _event_to_entry(
    ev: dict[str, object],
    spawn_id: str,
    ident: str,
    ctx_pct: float | None,
) -> dict[str, object] | None:
    etype = ev.get("type")
    if etype == "tool_call":
        return {
            "spawn": spawn_id[:8],
            "agent": ident,
            "entry_type": "tool",
            "name": ev.get("name"),
            "args": str(ev.get("arguments", "")),
            "ctx_pct": int(ctx_pct) if ctx_pct is not None else None,
            "content": None,
        }
    if etype == "text":
        content = ev.get("content")
        if content:
            return {
                "spawn": spawn_id[:8],
                "agent": ident,
                "entry_type": "text",
                "content": str(content),
                "name": None,
                "args": None,
                "ctx_pct": int(ctx_pct) if ctx_pct is not None else None,
            }
    if etype == "tool_result":
        return {
            "spawn": spawn_id[:8],
            "agent": ident,
            "entry_type": "result",
            "name": ev.get("name"),
            "content": str(ev.get("content", "")),
            "args": None,
            "ctx_pct": int(ctx_pct) if ctx_pct is not None else None,
        }
    return None


def fetch_spawn_entries(
    s,
    agent_cache: dict[str, str],
) -> list[tuple[str, dict[str, object]]]:
    ident = _resolve_handle(s.agent_id, agent_cache)
    agent_obj = agents_mod.get(s.agent_id)
    model = agent_obj.model if agent_obj else None
    path = spawn_path_by_id(s.id)
    if not path:
        return []
    provider = path.parent.name
    provider_cls = (
        providers.get_provider(provider) if provider in providers.PROVIDER_NAMES else None
    )
    tool_map: dict[str, str] = {}

    timed: list[tuple[str, dict[str, object]]] = []
    ctx_pct: float | None = None
    with path.open() as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                ts = raw.get("timestamp") or ""
                inp = input_tokens_from_event(raw, provider)
                if inp > 0:
                    ctx_limit = providers.models.context_limit(model or "")
                    ctx_pct = max(0, 100 - inp / ctx_limit * 100)
                events: list[dict[str, object]] = [raw]
                if provider_cls and raw.get("type") not in ("assistant", "result"):
                    normalized = provider_cls.normalize_event(raw, ident, tool_map)
                    events = normalized if normalized else []
                for ev in events:
                    event_ts = ev.get("timestamp") or ts
                    ts_str = event_ts if isinstance(event_ts, str) else ""
                    entry = _event_to_entry(ev, s.id, ident, ctx_pct)
                    if entry:
                        timed.append((ts_str, entry))
            except json.JSONDecodeError:
                pass
    return timed


def parse_spawn_file(
    s,
    agent_cache: dict[str, str],
) -> list[tuple[str, str]]:
    ident = _resolve_handle(s.agent_id, agent_cache)
    agent_obj = agents_mod.get(s.agent_id)
    model = agent_obj.model if agent_obj else None
    path = spawn_path_by_id(s.id)
    if not path:
        return []

    mtime = path.stat().st_mtime
    if path in _RENDER_CACHE:
        cached_mtime, cached_data = _RENDER_CACHE.pop(path)
        if cached_mtime == mtime:
            _RENDER_CACHE[path] = (cached_mtime, cached_data)
            return cached_data

    provider = path.parent.name
    provider_cls = (
        providers.get_provider(provider) if provider in providers.PROVIDER_NAMES else None
    )
    tool_map: dict[str, str] = {}

    timed: list[tuple[str, str]] = []
    ctx_pct: float | None = None
    with path.open() as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                ts = raw.get("timestamp") or ""

                if raw.get("type") == "daemon":
                    timed.append(
                        (ts, _format_daemon_event(ident, raw.get("action", ""), raw.get("reason")))
                    )
                    continue

                if raw.get("type") == "context_init" and raw.get("context_case") == "RESUME":
                    timed.append((ts, _format_resume_event(ident)))
                    continue

                inp = input_tokens_from_event(raw, provider)
                if inp > 0:
                    ctx_limit = providers.models.context_limit(model or "")
                    ctx_pct = max(0, 100 - inp / ctx_limit * 100)
                events: list[dict[str, object]] = [raw]
                if provider_cls and raw.get("type") not in ("assistant", "result"):
                    normalized = provider_cls.normalize_event(raw, ident, tool_map)
                    events = normalized if normalized else []
                for ev in events:
                    event_ts = ev.get("timestamp") or ts
                    ts_str = event_ts if isinstance(event_ts, str) else ""
                    timed.extend(
                        (ts_str, fmt)
                        for fmt in trace.format_event_multi(ev, ident, ctx_pct, tool_map=tool_map)
                    )
            except json.JSONDecodeError:
                pass

    _RENDER_CACHE[path] = (mtime, timed)
    if len(_RENDER_CACHE) > 1000:
        _RENDER_CACHE.pop(next(iter(_RENDER_CACHE)))
    return timed


def generate_tail(target_date: date) -> list[str]:
    agent_cache: dict[str, str] = {}

    all_spawns = spawn.fetch(limit=500)
    day_spawns = [s for s in all_spawns if _local_date(s.created_at) == target_date]

    if not day_spawns:
        return []

    timed: list[tuple[str, str]] = []
    for s in day_spawns:
        timed.extend(parse_spawn_file(s, agent_cache))

    timed.sort(key=lambda t: t[0])
    return [ansi.strip_markdown(ansi.strip(fmt)).lower() for _, fmt in timed]


def tail_dir() -> Path:
    return paths.dot_space() / "tail"


def tail_path(target_date: date) -> Path:
    return tail_dir() / f"{target_date.isoformat()}.txt"


def save_tail(target_date: date) -> dict[str, int | str]:
    lines = generate_tail(target_date)
    if not lines:
        return {"lines": 0}

    out = tail_dir()
    out.mkdir(parents=True, exist_ok=True)
    dest = tail_path(target_date)
    with tempfile.NamedTemporaryFile("w", dir=out, delete=False) as f:
        f.write("\n".join(lines))
        temp_path = f.name

    Path(temp_path).replace(dest)

    return {"lines": len(lines), "path": str(dest)}


def _flush_pending_text(
    t: StreamState,
    out: list[tuple[str, str]],
    verbose: bool = False,
    identities: set[str] | None = None,
) -> None:
    if not t.pending_text:
        return
    ev: dict[str, object] = {
        "type": "text",
        "content": t.pending_text,
    }
    fmt_str = trace.format_event(ev, t.handle, t.ctx_pct, verbose=verbose, identities=identities)
    if fmt_str:
        out.append(("", fmt_str))
    t.pending_text = ""


def read_stream(
    t: StreamState,
    verbose: bool = False,
    flush: bool = False,
    identities: set[str] | None = None,
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    try:
        if t.path.stat().st_size <= t.position:
            return out
        provider = t.path.parent.name
        provider_cls = (
            providers.get_provider(provider) if provider in providers.PROVIDER_NAMES else None
        )
        if t.tool_map is None:
            t.tool_map = {}
        with t.path.open() as f:
            f.seek(t.position)
            for line in f:
                line = line.rstrip()
                if line:
                    try:
                        raw = json.loads(line)
                        t.lines_read += 1

                        if raw.get("type") == "daemon":
                            _flush_pending_text(t, out, verbose=verbose, identities=identities)
                            out.append(
                                (
                                    "",
                                    _format_daemon_event(
                                        t.handle, raw.get("action", ""), raw.get("reason")
                                    ),
                                )
                            )
                            continue

                        if (
                            raw.get("type") == "context_init"
                            and raw.get("context_case") == "RESUME"
                        ):
                            _flush_pending_text(t, out, verbose=verbose, identities=identities)
                            out.append(("", _format_resume_event(t.handle)))
                            continue

                        inp = input_tokens_from_event(raw, provider)
                        if inp > 0:
                            ctx_limit = providers.models.context_limit(t.model or "")
                            t.ctx_pct = max(0, 100 - inp / ctx_limit * 100)
                            t.has_real_usage = True

                        events: list[dict[str, object]] = [raw]
                        if provider_cls and raw.get("type") not in ("assistant", "result"):
                            normalized = provider_cls.normalize_event(raw, t.handle, t.tool_map)
                            events = normalized if normalized else []

                        for ev in events:
                            etype = ev.get("type")
                            if etype == "text":
                                chunk = provider_base.stringify_content(ev.get("content"))
                                t.cumulative_chars += len(chunk)
                                t.turns += 1
                                t.pending_text += chunk
                                continue

                            if etype == "tool_call":
                                tc = ev.get("content")
                                if isinstance(tc, dict):
                                    if str(tc.get("tool_name")) == "Bash":
                                        inp = tc.get("input", {})
                                        cmd = (
                                            inp.get("command", "") if isinstance(inp, dict) else ""
                                        )
                                        cd_path = extract_cd(cmd)
                                        if cd_path:
                                            t.cwd = cd_path
                                    t.cumulative_chars += len(
                                        json.dumps(tc.get("input", {}), default=str)
                                    )
                            elif etype == "tool_result":
                                tc = ev.get("content")
                                if isinstance(tc, dict):
                                    tr_out = tc.get("output", "")
                                    if isinstance(tr_out, str):
                                        t.cumulative_chars += len(tr_out)

                            if not t.has_real_usage and t.cumulative_chars > 0:
                                t.ctx_pct = estimate_ctx_pct(
                                    t.cumulative_chars, t.turns, t.model, provider
                                )

                            _flush_pending_text(t, out, verbose=verbose, identities=identities)
                            fmt_str = trace.format_event(
                                ev,
                                t.handle,
                                t.ctx_pct,
                                verbose=verbose,
                                tool_map=t.tool_map,
                                identities=identities,
                            )
                            if fmt_str:
                                out.append(("", fmt_str))
                    except json.JSONDecodeError:
                        pass
            if flush:
                _flush_pending_text(t, out, verbose=verbose, identities=identities)
            t.position = f.tell()
    except (OSError, FileNotFoundError):
        pass
    if not out and t.lines_read > 0 and not t.shown_starting:
        prefix = format_nameplate(t.handle, t.ctx_pct)
        wake = random.choice(trace.WAKE_PHRASES)  # noqa: S311
        out.append(("", f"{prefix} {ansi.white(wake)}"))
        t.shown_starting = True
    return out


def _spawn_error(s: Spawn | None, sid: str) -> str | None:
    if s and s.error:
        return _clean_error_display(s.error)
    try:
        raw = spawn.get(SpawnId(sid)).error
        return _clean_error_display(raw) if raw else None
    except Exception:
        return None


def _clean_error_display(error: str) -> str:
    from space.agents.spawn import run  # noqa: PLC0415

    if any(k in error for k in ("launch failed:", "spawn failed:")):
        return run.clean_stderr(error)
    return error[:80]


def _render_history_chronological(
    spawn_list: list[Spawn],
    agent_cache: dict[str, str],
):
    timed: list[tuple[str, str]] = []
    for s in spawn_list:
        timed.extend(parse_spawn_file(s, agent_cache))
    timed.sort(key=lambda t: t[0])
    for _, fmt in timed:
        yield fmt


def _filter_by_agent(
    spawn_list: list[Spawn],
    agent: str | None,
    agent_cache: dict[str, str],
) -> list[Spawn]:
    if not agent:
        return spawn_list
    return [
        s
        for s in spawn_list
        if _resolve_handle(s.agent_id, agent_cache).lower().startswith(agent.lower())
    ]


def _fetch_recent_spawns(
    since_minutes: int,
    agent: str | None,
    agent_cache: dict[str, str],
) -> list[Spawn]:
    since_iso = (datetime.now(UTC) - timedelta(minutes=since_minutes)).isoformat()
    active = spawn.fetch(status=SpawnStatus.ACTIVE)
    recent = spawn.fetch(since=since_iso)
    seen = {s.id for s in active}
    all_spawns = active + [s for s in recent if s.id not in seen]
    return _filter_by_agent(all_spawns, agent, agent_cache)


def tail_spawns(
    lines: int = 20,
    agent: str | None = None,
    verbose: bool = False,
    since_minutes: int | None = None,
    watch: bool = False,
):
    agent_cache: dict[str, str] = {}
    effective_since = since_minutes if since_minutes is not None else 10
    recent_spawns = _fetch_recent_spawns(effective_since, agent, agent_cache)

    yield f"{ansi.mention('swarm')} {ansi.bold('brr')}"
    if recent_spawns:
        for line in _render_history_chronological(recent_spawns, agent_cache):
            yield line

    if not watch:
        return

    streams: dict[str, StreamState] = {}
    seen_error_ids: set[str] = set()

    def _sync() -> tuple[list[tuple[str, float | None]], list[tuple[str, str | None]]]:
        current = spawn.fetch(status=SpawnStatus.ACTIVE)
        current = _filter_by_agent(current, agent, agent_cache)
        spawn_map = {s.id: s for s in current}
        active_ids = set(spawn_map.keys())
        current_ids = set(streams.keys())
        added: list[tuple[str, float | None]] = []
        removed: list[tuple[str, str | None]] = []
        for s in current:
            if s.id in current_ids or s.id in seen_error_ids:
                continue
            if s.status == SpawnStatus.DONE and s.error:
                ag = agents_mod.get(s.agent_id)
                handle = ag.handle if ag else s.agent_id[:8]
                removed.append((handle, s.error))
                seen_error_ids.add(s.id)
                continue
            path = spawn_path(s, agent_cache)
            if path:
                ag = agents_mod.get(s.agent_id)
                handle = ag.handle if ag else s.agent_id[:8]
                model = ag.model if ag else None
                u = spawn.usage(s)
                pct = u.get("percentage") if u else None
                stat = path.stat()
                if (
                    s.status != SpawnStatus.ACTIVE
                    and (time.time() - stat.st_mtime) > _STALE_THRESHOLD_SECONDS
                ):
                    continue
                pos = max(0, stat.st_size - 8192)
                streams[s.id] = StreamState(
                    s.id, handle, path, pos, ctx_pct=pct, model=model, shown_starting=True
                )
                added.append((handle, pct))
        for sid in current_ids - active_ids:
            error = _spawn_error(spawn_map.get(SpawnId(sid)), sid)
            removed.append((streams[sid].handle, error))
            del streams[sid]
        for sid in list(streams):
            try:
                if sid in active_ids:
                    continue
                if (time.time() - streams[sid].path.stat().st_mtime) > _STALE_THRESHOLD_SECONDS:
                    error = _spawn_error(None, sid)
                    removed.append((streams[sid].handle, error))
                    del streams[sid]
            except OSError:
                del streams[sid]
        return added, removed

    seen_identities: set[str] = {_resolve_handle(s.agent_id, agent_cache) for s in recent_spawns}
    added, _removed = _sync()
    for handle, pct in added:
        wake = random.choice(trace.WAKE_PHRASES)  # noqa: S311
        yield f"{format_nameplate(handle, pct)} {ansi.white(wake)}"
    last_sync = time.time()

    try:
        while True:
            for t in list(streams.values()):
                for _, line in read_stream(t, verbose=verbose, identities=seen_identities):
                    yield line
            if time.time() - last_sync > 1.0:
                added, removed = _sync()
                for handle, pct in added:
                    if handle not in seen_identities:
                        wake = random.choice(trace.WAKE_PHRASES)  # noqa: S311
                        yield f"{format_nameplate(handle, pct)} {ansi.white(wake)}"
                        seen_identities.add(handle)
                if removed:
                    for handle, error in removed:
                        if error:
                            yield (
                                f"{format_nameplate(handle, None)} "
                                f"{ansi.bold(ansi.red('oops.'))} {ansi.coral(error)}"
                            )
                        else:
                            yield f"{ansi.mention(handle)} {ansi.dim('~ done')}"
                last_sync = time.time()
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass


def replay_date(
    target_date: date,
    agent: str | None = None,
) -> list[str]:
    cached = tail_path(target_date)
    if not agent and cached.exists():
        with cached.open() as f:
            return [line.rstrip() for line in f]

    agent_cache: dict[str, str] = {}
    start = datetime.combine(target_date, datetime.min.time()).isoformat()
    end = datetime.combine(target_date, datetime.max.time()).isoformat()

    all_spawns = spawn.fetch(since=start)
    day_spawns = [s for s in all_spawns if s.created_at and s.created_at <= end]

    if agent:
        day_spawns = [
            s
            for s in day_spawns
            if _resolve_handle(s.agent_id, agent_cache).lower().startswith(agent.lower())
        ]

    if not day_spawns:
        return []

    timed: list[tuple[str, str]] = []
    for s in day_spawns:
        timed.extend(parse_spawn_file(s, agent_cache))

    timed.sort(key=lambda t: t[0])
    return [fmt for _, fmt in timed]
