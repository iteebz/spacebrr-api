import contextlib
import logging
import os
import signal
import sqlite3
import subprocess
import time
from datetime import UTC, datetime, timedelta
from threading import Lock, Thread
from typing import Any

from space.core.models import Spawn, SpawnStatus, TaskStatus
from space.core.types import AgentId, SpawnId
from space.ledger import tasks
from space.lib import store

from . import repo

logger = logging.getLogger(__name__)

_active_processes: dict[str, subprocess.Popen[Any]] = {}
_process_lock = Lock()


def clear_process(spawn_id: SpawnId) -> None:
    with _process_lock:
        _active_processes.pop(spawn_id, None)


def set_pid(spawn_id: SpawnId, pid: int, proc: subprocess.Popen[Any] | None = None) -> bool:
    success = repo.set_pid_atomic(spawn_id, pid)
    if success and proc:
        with _process_lock:
            _active_processes[spawn_id] = proc
    elif not success and proc:
        logger.warning(
            "PID race detected for spawn %s, killing duplicate process %d", spawn_id[:8], pid
        )
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
    return success


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def terminate(spawn_id: SpawnId) -> Spawn:
    s = repo.get(spawn_id)
    if s.status == SpawnStatus.DONE:
        return s
    _kill_if_alive(s.id, s.pid)
    return repo.update(s.id, status=SpawnStatus.DONE, error="terminated")


def _kill_if_alive(spawn_id: SpawnId, pid: int | None) -> bool:
    with _process_lock:
        proc = _active_processes.pop(spawn_id, None)

    if proc:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        Thread(target=_reap_process, args=(proc,), daemon=True).start()
        return True

    if not pid or not _pid_alive(pid):
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        return True
    except (ProcessLookupError, ChildProcessError):
        return False
    except OSError as e:
        logger.error(f"Kill failed for spawn {spawn_id}: {e}")
        return False


def _reap_process(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, subprocess.TimeoutExpired):
        proc.wait(timeout=0.5)


REAP_GRACE_SECONDS = 30


def reap() -> int:
    cleaned = 0
    now = datetime.now(UTC)
    grace_cutoff = (now - timedelta(seconds=REAP_GRACE_SECONDS)).isoformat()
    now_str = now.isoformat()

    with store.ensure() as conn:
        rows = conn.execute(
            "SELECT id, pid FROM spawns WHERE status = 'active' AND created_at < ?",
            (grace_cutoff,),
        ).fetchall()

    dead_spawns = []
    for spawn_id, pid in rows:
        if pid is None:
            dead_spawns.append(spawn_id)
        else:
            try:
                os.kill(pid, 0)
            except OSError:
                dead_spawns.append(spawn_id)

    for spawn_id in dead_spawns:
        _finalize_orphan(spawn_id)

    with store.write() as conn:
        for spawn_id in dead_spawns:
            cursor = conn.execute(
                "UPDATE spawns SET status = ?, last_active_at = ?, error = ?, pid = NULL WHERE id = ? AND status = 'active'",
                ("done", now_str, "reaped", spawn_id),
            )
            if cursor.rowcount > 0:
                cleaned += 1

    return cleaned


def _finalize_orphan(spawn_id: str) -> None:
    from . import integrity, trace  # noqa: PLC0415

    try:
        events_file = trace.events_file_path(spawn_id)
        if events_file and events_file.exists():
            integrity.finalize(SpawnId(spawn_id), events_file)

            stderr_file = events_file.with_suffix(".stderr")
            if stderr_file.exists():
                stderr = stderr_file.read_text()
                if stderr and "No conversation found" in stderr:
                    repo.update(SpawnId(spawn_id), session_id="")

        _autofill_summary(spawn_id)
    except Exception:
        logger.debug("finalize_orphan failed for %s", spawn_id[:8])


def _autofill_summary(spawn_id: str) -> None:
    from . import trace  # noqa: PLC0415

    try:
        s = repo.get(SpawnId(spawn_id))
        if s.summary:
            return
        auto = trace.extract_last_response(spawn_id)
        if auto:
            repo.update(SpawnId(spawn_id), summary=auto)
    except Exception:
        logger.debug("autofill_summary failed for %s", spawn_id[:8])


def reconcile() -> tuple[int, int]:
    killed = 0
    marked_dead = reap()

    with store.ensure() as conn:
        rows = conn.execute(
            "SELECT id, pid FROM spawns WHERE pid IS NOT NULL AND status = 'done'",
        ).fetchall()

    for spawn_id, pid in rows:
        if _pid_alive(pid):
            logger.warning("reconcile spawn=%s pid=%d alive but done, killing", spawn_id[:8], pid)
            _kill_if_alive(SpawnId(spawn_id), pid)
            killed += 1
        with store.write() as conn:
            conn.execute("UPDATE spawns SET pid = NULL WHERE id = ?", (spawn_id,))

    return killed, marked_dead


def stop(agent_id: AgentId) -> Spawn | None:
    spawns = repo.fetch(agent_id=agent_id, status=SpawnStatus.ACTIVE, limit=1)
    if not spawns:
        return None
    return terminate(spawns[0].id)


def get_checklist(spawn: Spawn) -> dict[str, Any]:
    all_tasks = tasks.fetch(assignee_id=spawn.agent_id)
    owned_tasks = [t for t in all_tasks if t.status == TaskStatus.ACTIVE]

    return {
        "spawn_id": spawn.id,
        "summary": spawn.summary,
        "tasks_owned": len(owned_tasks),
        "tasks": [{"task_id": t.id, "content": t.content[:100]} for t in owned_tasks[:5]],
    }


MIN_SUMMARY_LENGTH = 10


def done(spawn: Spawn, summary: str) -> dict[str, Any]:
    summary = summary.strip()
    if len(summary) < MIN_SUMMARY_LENGTH:
        return {
            "spawn_id": spawn.id,
            "error": f"Summary too short ({len(summary)} chars). Minimum {MIN_SUMMARY_LENGTH}.",
        }
    try:
        repo.update(spawn.id, status=SpawnStatus.DONE, summary=summary)
    except sqlite3.IntegrityError as e:
        active = repo.fetch(
            agent_id=spawn.agent_id,
            status=SpawnStatus.ACTIVE,
            limit=5,
        )
        active_ids = [s.id[:8] for s in active]
        return {
            "spawn_id": spawn.id,
            "error": (
                f"DB constraint failed while sleeping: {e} "
                f"(spawn={spawn.id[:8]} agent={spawn.agent_id[:8]} "
                f"active={active_ids})"
            ),
        }
    return {
        "spawn_id": spawn.id,
        "summary": summary,
    }
