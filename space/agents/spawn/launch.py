
from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from space import agents
from space.core.errors import StateError
from space.core.models import Agent, Spawn, SpawnMode, SpawnStatus
from space.core.types import AgentId, SpawnId
from space.lib import config, hooks, paths, providers, tools

from . import repo

logger = logging.getLogger(__name__)

MAX_ERR_LEN = 200


def _launch_error_message(exc: Exception) -> str:
    detail = f"{type(exc).__name__}: {exc}".strip()
    if len(detail) > MAX_ERR_LEN:
        detail = detail[: MAX_ERR_LEN - 1] + "…"
    return f"launch failed: {detail}"


def _resolve_cwd() -> str:
    from space.ledger import projects  # noqa: PLC0415

    if (project := projects.infer_from_cwd()) and project.repo_path:
        return project.repo_path
    return str(Path.home() / "space")


def launch(
    agent_id: AgentId,
    *,
    instruction: str | None = None,
    images: list[str] | None = None,
    spawn: Spawn | None = None,
    cwd: str | None = None,
    timeout_seconds: int = 3600,
    caller_spawn_id: SpawnId | None = None,
    model_override: str | None = None,
    mode: SpawnMode = SpawnMode.SOVEREIGN,
    skills: list[str] | None = None,
    write_starting_event: bool = False,
) -> Spawn:
    agent = agents.get(agent_id)
    effective_agent = agent
    if model_override and model_override != agent.model:
        from dataclasses import replace  # noqa: PLC0415

        effective_agent = replace(agent, model=model_override)

    s, is_resume, is_new = _resolve_spawn(effective_agent, spawn, caller_spawn_id, mode=mode)
    env = _build_env(s, effective_agent)
    resolved_cwd = cwd or _resolve_cwd()
    cwd_path = Path(resolved_cwd) if resolved_cwd else None

    from space import ctx  # noqa: PLC0415

    ctx.inject(s, effective_agent, cwd_path)

    if is_resume:
        context = ctx.resume(instruction or "continue", images=images, spawn=s, cwd=resolved_cwd)
    else:
        from space.ctx.prompt import wake as prompt_wake  # noqa: PLC0415

        context = prompt_wake(s, skills=skills)

    _launch_background(
        agent=effective_agent,
        s=s,
        is_resume=is_resume,
        context=context,
        images=images if is_resume else None,
        env=env,
        cwd=resolved_cwd,
        timeout_seconds=timeout_seconds,
    )

    result = repo.get(s.id)
    if write_starting_event and is_new:
        write_daemon_event(result.id, "starting")
    return result


def _resolve_spawn(
    agent: Agent,
    s: Spawn | None,
    caller_spawn_id: SpawnId | None,
    mode: SpawnMode = SpawnMode.SOVEREIGN,
) -> tuple[Spawn, bool, bool]:
    if s:
        if s.status == SpawnStatus.ACTIVE and s.pid:
            raise StateError(f"Spawn '{s.id}' is already running (pid {s.pid})")
        if s.status == SpawnStatus.DONE and not s.session_id:
            raise StateError(f"Spawn '{s.id}' is DONE with no session, cannot resume")
        is_resume = bool(s.session_id)
        return repo.update(s.id, status=SpawnStatus.ACTIVE), is_resume, False

    caller_id = caller_spawn_id or (SpawnId(cid) if (cid := paths.spawn_id()) else None)
    s, created = repo.get_or_create(
        agent.id,
        caller_spawn_id=caller_id,
        mode=mode,
    )

    is_resume = not created and bool(s.session_id)
    return repo.update(s.id, status=SpawnStatus.ACTIVE), is_resume, created


def _launch_background(
    agent: Agent,
    s: Spawn,
    is_resume: bool,
    context: str,
    images: list[str] | None,
    env: dict[str, str],
    cwd: str,
    timeout_seconds: int,
) -> None:
    if not agent.model:
        raise StateError(f"Agent {agent.handle} has no model")

    provider = providers.map(agent.model)
    blocked_until = providers.router.provider_blocked_until(provider)
    if blocked_until:
        raise StateError(
            f"Provider {provider} is blocked until {blocked_until.isoformat()} due to quota"
        )
    _write_context_event(s.id, provider, "RESUME" if is_resume else "WAKE", context)

    cmd, stdin_content = _build_command(agent, s.session_id, context, cwd, images=images)
    identity_dir = paths.identity_dir(agent.handle)
    identity_dir.mkdir(parents=True, exist_ok=True)

    merged_env = {**os.environ, **env}

    stdin_file = None
    if stdin_content:
        stdin_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        stdin_file.write(stdin_content)
        stdin_file.close()

    _spawn_sovereign(cmd, identity_dir, merged_env, stdin_file, s, agent, timeout_seconds)


def _spawn_sovereign(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    stdin_file: tempfile._TemporaryFileWrapper[str] | None,
    s: Spawn,
    agent: Agent,
    timeout_seconds: int,
) -> None:
    if not agent.model:
        raise StateError(f"Agent {agent.handle} has no model")
    provider = providers.map(agent.model)
    events_file = paths.dot_space() / "spawns" / provider / f"{s.id}.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    stderr_file = events_file.with_suffix(".stderr")

    stdin_path = Path(stdin_file.name) if stdin_file else None
    try:
        stdin_handle = stdin_path.open() if stdin_path else None
        stdout_fd = events_file.open("a")
        stderr_fd = stderr_file.open("a")

        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdin=stdin_handle or subprocess.DEVNULL,
            stdout=stdout_fd,
            stderr=stderr_fd,
            start_new_session=True,
        )

        from . import lifecycle  # noqa: PLC0415

        pid_set = lifecycle.set_pid(s.id, proc.pid, proc)

        if stdin_handle:
            stdin_handle.close()
        stdout_fd.close()
        stderr_fd.close()

        if not pid_set:
            logger.info("Spawn %s lost PID race, aborting launch", s.id[:8])
            return
    finally:
        if stdin_path:
            stdin_path.unlink(missing_ok=True)

    def _monitor() -> None:
        try:
            _monitor_sovereign(proc, s, agent, events_file, stderr_file, timeout_seconds)
        except Exception as exc:
            with contextlib.suppress(Exception):
                logger.exception("Sovereign spawn %s monitor failed", s.id[:8])
            with contextlib.suppress(Exception):
                repo.update(
                    s.id,
                    status=SpawnStatus.DONE,
                    error=_launch_error_message(exc),
                )
            with contextlib.suppress(Exception):
                hooks.run_all(repo.get(s.id))

    t = threading.Thread(target=_monitor, daemon=True)
    t.start()


def _monitor_sovereign(
    proc: subprocess.Popen[bytes],
    s: Spawn,
    agent: Agent,
    events_file: Path,
    stderr_file: Path,
    timeout_seconds: int,
) -> None:
    import time  # noqa: PLC0415

    provider = providers.map(agent.model) if agent.model else "unknown"
    deadline = time.monotonic() + timeout_seconds
    file_pos = 0
    session_id: str | None = None

    while proc.poll() is None:
        if time.monotonic() > deadline:
            proc.kill()
            proc.wait()
            from space.agents.spawn import lifecycle as _lc  # noqa: PLC0415

            _lc.clear_process(s.id)
            repo.update(s.id, status=SpawnStatus.DONE, error="timeout")
            hooks.run_all(repo.get(s.id))
            return
        file_pos, session_id = _tail_events(events_file, file_pos, s.id, session_id)
        time.sleep(1)

    _tail_events(events_file, file_pos, s.id, session_id)

    from space.agents.spawn import integrity, lifecycle, run, trace  # noqa: PLC0415

    lifecycle.clear_process(s.id)

    current = repo.get(s.id)
    if current.status == SpawnStatus.DONE:
        return

    stderr = stderr_file.read_text() if stderr_file.exists() else ""

    result = run.Result(proc.returncode, stderr)
    run.handle_exit(result, s.id, provider, session_id)

    integrity.finalize(s.id, events_file)
    trace.clear(s.id)

    current = repo.get(s.id)
    if current.status == SpawnStatus.ACTIVE:
        repo.update(s.id, status=SpawnStatus.DONE, error="no summary")

    lifecycle._autofill_summary(s.id)
    hooks.run_all(repo.get(s.id))


def _tail_events(
    events_file: Path, pos: int, spawn_id: str, session_id: str | None
) -> tuple[int, str | None]:
    import json as _json  # noqa: PLC0415

    from space.agents.spawn import run, trace  # noqa: PLC0415

    try:
        with events_file.open() as f:
            f.seek(pos)
            for line in f:
                try:
                    event = _json.loads(line)
                    event_type = event.get("type")
                    subtype = event.get("subtype")
                    for (etype, sub), field in run.SESSION_CAPTURE_EVENTS.items():
                        if (
                            event_type == etype
                            and (sub is None or subtype == sub)
                            and field in event
                        ):
                            session_id = event[field]
                            current = repo.get(SpawnId(spawn_id))
                            if current and current.session_id != session_id:
                                repo.update(current.id, session_id=session_id)
                            break
                    trace.publish(spawn_id, event)
                    if event_type in run.TOUCH_EVENTS:
                        repo.touch(SpawnId(spawn_id))
                except (_json.JSONDecodeError, ValueError):
                    pass
            new_pos = f.tell()
    except FileNotFoundError:
        return pos, session_id
    return new_pos, session_id


def _build_env(s: Spawn, agent: Agent) -> dict[str, str]:
    env = os.environ.copy()
    env["SPACE_SPAWN_ID"] = s.id
    env["SPACE_IDENTITY"] = agent.handle
    env["GIT_AUTHOR_NAME"] = agent.handle
    env["GIT_AUTHOR_EMAIL"] = f"{agent.handle}@space.local"
    env["GIT_COMMITTER_NAME"] = agent.handle
    env["GIT_COMMITTER_EMAIL"] = f"{agent.handle}@space.local"
    env["GIT_CONFIG_GLOBAL"] = str(paths.identity_dir(agent.handle) / ".gitconfig")

    cfg = config.load().swarm
    env["SPACE_SWARM_CONCURRENCY"] = str(cfg.concurrency)
    if cfg.limit is not None and cfg.enabled_at:
        launched = repo.fetch(since=cfg.enabled_at)
        remaining = max(0, cfg.limit - len(launched))
        env["SPACE_SWARM_REMAINING"] = str(remaining)

    return env


def _build_command(
    agent: Agent,
    session_id: str | None,
    context: str,
    cwd: str | None = None,
    images: list[str] | None = None,
) -> tuple[list[str], str | None]:
    if not agent.model:
        raise StateError(f"Agent {agent.handle} has no model")
    provider = providers.map(agent.model)
    provider_cls = providers.get_provider(provider)

    allowed_tools: set[tools.Tool] | None = None
    if agent.identity:
        try:
            const = agents.identity.load(agent.identity)
            allowed_tools = const.tools
        except Exception:
            logger.debug("Failed to load identity %s, using default tools", agent.identity)

    # Codex prioritizes workspace AGENTS.md when --cd points at the lattice root.
    # Prepend the injected system context so per-agent identities still apply.
    if provider == "codex":
        from space import ctx  # noqa: PLC0415

        context = f"{ctx.build(agent)}\n\n{context}"

    cmd, stdin = provider_cls.build_command(
        model=agent.model,
        session_id=session_id,
        context=context,
        root_dir=str(paths.space_root()),
        cwd=cwd,
        allowed_tools=allowed_tools,
        images=images,
    )

    return cmd, stdin


def _write_context_event(spawn_id: SpawnId, provider: str, context_case: str, context: str) -> None:
    events_file = paths.dot_space() / "spawns" / provider / f"{spawn_id}.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "type": "context_init",
        "context_case": context_case,
        "context": context,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    with Path(events_file).open("a") as f:
        f.write(json.dumps(event) + "\n")


def write_daemon_event(spawn_id: SpawnId, action: str, reason: str | None = None) -> None:
    s = repo.get(spawn_id)
    agent = agents.get(s.agent_id)
    if not agent.model:
        return
    provider = providers.map(agent.model)
    events_file = paths.dot_space() / "spawns" / provider / f"{spawn_id}.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "type": "daemon",
        "action": action,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if reason:
        event["reason"] = reason
    with Path(events_file).open("a") as f:
        f.write(json.dumps(event) + "\n")
