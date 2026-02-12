import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from space.core import ids
from space.core.errors import NotFoundError, ValidationError
from space.core.models import Spawn, SpawnMode, SpawnStatus
from space.core.types import UNSET, AgentId, SpawnId, Unset
from space.lib import citations, store
from space.lib.store.health import rebuild_fts
from space.lib.store.sqlite import placeholders


def parse_status_filter(status: str | Sequence[str] | None) -> list[str] | None:
    if not status:
        return None
    if isinstance(status, str):
        return status.split("|") if "|" in status else [status]
    return list(status)


SPAWN_SELECT = "SELECT * FROM spawns"


def create(
    agent_id: AgentId,
    *,
    caller_spawn_id: SpawnId | None = None,
    mode: SpawnMode = SpawnMode.SOVEREIGN,
) -> Spawn:
    spawn_id = SpawnId(ids.generate("spawns"))
    now = datetime.now(UTC).isoformat()

    with store.write() as conn:
        store.unarchive("agents", agent_id, conn)
        conn.execute(
            """
            INSERT INTO spawns
            (id, agent_id, caller_spawn_id, status, mode, created_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (spawn_id, agent_id, caller_spawn_id, mode.value, now),
        )

    return Spawn(
        id=spawn_id,
        agent_id=agent_id,
        caller_spawn_id=caller_spawn_id,
        status=SpawnStatus.ACTIVE,
        mode=mode,
        pid=None,
        session_id=None,
        created_at=now,
        last_active_at=None,
        summary=None,
    )


def get_or_create(
    agent_id: AgentId,
    *,
    caller_spawn_id: SpawnId | None = None,
    mode: SpawnMode = SpawnMode.SOVEREIGN,
) -> tuple[Spawn, bool]:
    spawn_id = SpawnId(ids.generate("spawns"))
    now = datetime.now(UTC).isoformat()

    with store.write() as conn:
        store.unarchive("agents", agent_id, conn)

        cursor = conn.execute(
            """
            INSERT INTO spawns
            (id, agent_id, caller_spawn_id, status, mode, created_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            ON CONFLICT(agent_id) WHERE status = 'active' AND mode = 'sovereign'
            DO NOTHING
            """,
            (spawn_id, agent_id, caller_spawn_id, mode.value, now),
        )
        if cursor.rowcount == 0:
            row = conn.execute(
                SPAWN_SELECT + " WHERE agent_id = ? AND status = 'active' AND mode = ?",
                (agent_id, mode.value),
            ).fetchone()
            if row:
                return store.from_row(row, Spawn), False
            raise RuntimeError("TOCTOU race: spawn disappeared")

    return (
        Spawn(
            id=spawn_id,
            agent_id=agent_id,
            caller_spawn_id=caller_spawn_id,
            status=SpawnStatus.ACTIVE,
            mode=mode,
            pid=None,
            session_id=None,
            created_at=now,
            last_active_at=None,
            summary=None,
        ),
        True,
    )


def update(
    spawn_id: SpawnId,
    *,
    status: SpawnStatus | None = None,
    pid: int | None | Unset = UNSET,
    session_id: str | None = None,
    summary: str | None = None,
    error: str | None | Unset = UNSET,
) -> Spawn:
    if status == SpawnStatus.DONE and summary is None and error is UNSET:
        raise ValidationError("Spawn completion requires summary or error")

    updates: list[str] = []
    params: list[str | int] = []

    if status is not None:
        status_str = status.value
        updates.append("status = ?")
        params.append(status_str)

        now = datetime.now(UTC).isoformat()
        process_exited = status != SpawnStatus.ACTIVE
        if process_exited:
            updates.append("last_active_at = ?")
            params.append(now)
            updates.append("pid = NULL")
        else:
            updates.append("last_active_at = NULL")
            updates.append("error = NULL")

    if pid is not UNSET:
        if pid is None:
            updates.append("pid = NULL")
        else:
            updates.append("pid = ?")
            params.append(pid)

    if session_id is not None:
        updates.append("session_id = ?")
        params.append(session_id)

    summary_changed = False
    if summary is not None:
        updates.append("summary = ?")
        params.append(summary)
        summary_changed = True

    if error is not UNSET:
        if error is None:
            updates.append("error = NULL")
        else:
            updates.append("error = ?")
            params.append(error)

    if not updates:
        return get(spawn_id)

    def _do_update(conn: sqlite3.Connection) -> None:
        conn.execute(
            f"UPDATE spawns SET {', '.join(updates)} WHERE id = ?",  # noqa: S608 - hardcoded columns
            (*params, spawn_id),
        )
        if summary_changed and summary:
            conn.execute(
                "DELETE FROM citations WHERE source_type = 'spawn' AND source_id = ?", (spawn_id,)
            )
            citations.store(conn, "spawn", spawn_id, summary)

    try:
        with store.write() as conn:
            _do_update(conn)
    except sqlite3.IntegrityError:
        with store.write() as conn:
            rebuild_fts(conn, "spawns_fts")
        with store.write() as conn:
            _do_update(conn)
    return get(spawn_id)


def set_pid_atomic(spawn_id: SpawnId, pid: int) -> bool:
    with store.write() as conn:
        cursor = conn.execute(
            "UPDATE spawns SET pid = ? WHERE id = ? AND pid IS NULL",
            (pid, spawn_id),
        )
        return cursor.rowcount > 0


def touch(spawn_id: SpawnId) -> Spawn:
    now = datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            "UPDATE spawns SET last_active_at = ? WHERE id = ? AND status = 'active'",
            (now, spawn_id),
        )
    return get(spawn_id)


def get(spawn_id: SpawnId) -> Spawn:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM spawns WHERE id = ?", (spawn_id,)).fetchone()
        if not row:
            raise NotFoundError(spawn_id)
        return store.from_row(row, Spawn)


def fetch(
    agent_id: AgentId | None = None,
    caller_ids: list[SpawnId] | None = None,
    status: SpawnStatus | Sequence[SpawnStatus] | str | Sequence[str] | None = None,
    mode: SpawnMode | None = None,
    since: str | None = None,
    has_session: bool = False,
    limit: int | None = None,
    errors: list[str] | None = None,
    spawn_ids: list[SpawnId] | None = None,
) -> list[Spawn]:
    with store.ensure() as conn:
        query = SPAWN_SELECT + " WHERE 1=1"
        params: list[str | int] = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        if caller_ids:
            query += f" AND caller_spawn_id IN ({placeholders(caller_ids)})"
            params.extend(caller_ids)

        if status is not None:
            if isinstance(status, SpawnStatus):
                query += " AND status = ?"
                params.append(status.value)
            elif isinstance(status, str):
                statuses = parse_status_filter(status)
                if statuses:
                    query += f" AND status IN ({placeholders(statuses)})"
                    params.extend(statuses)
            else:
                status_values = [s.value if isinstance(s, SpawnStatus) else s for s in status]
                query += f" AND status IN ({placeholders(status_values)})"
                params.extend(status_values)

        if mode is not None:
            query += " AND mode = ?"
            params.append(mode.value)

        if since:
            query += " AND created_at >= ?"
            params.append(since)

        if has_session:
            query += " AND session_id IS NOT NULL AND session_id != ''"

        if errors:
            query += f" AND error IN ({placeholders(errors)})"
            params.extend(errors)

        if spawn_ids:
            query += f" AND id IN ({placeholders(spawn_ids)})"
            params.extend(spawn_ids)

        query += " ORDER BY created_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [store.from_row(row, Spawn) for row in rows]


def count(since: str | None = None) -> int:
    with store.ensure() as conn:
        if since:
            row = conn.execute(
                "SELECT COUNT(*) FROM spawns WHERE created_at >= ?", (since,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM spawns").fetchone()
        return row[0]


INERTIA_PATTERNS = (
    "%correctly idle%",
    "%correctly blocked%",
    "%swarm correctly%",
    "%no productive%",
    "%no actionable%",
    "%waiting state%",
)


def clear_inertia_summaries() -> int:
    conditions = " OR ".join("summary LIKE ?" for _ in INERTIA_PATTERNS)
    with store.write() as conn:
        cursor = conn.execute(
            f"UPDATE spawns SET summary = NULL WHERE {conditions}",  # noqa: S608
            INERTIA_PATTERNS,
        )
        return cursor.rowcount


def increment_resume_count(spawn_id: SpawnId) -> int:
    with store.write() as conn:
        conn.execute(
            "UPDATE spawns SET resume_count = COALESCE(resume_count, 0) + 1 WHERE id = ?",
            (spawn_id,),
        )
        row = conn.execute("SELECT resume_count FROM spawns WHERE id = ?", (spawn_id,)).fetchone()
        return row[0] if row else 0
