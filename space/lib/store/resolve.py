import sqlite3
from collections.abc import Callable

from space.core.errors import NotFoundError, ReferenceError, ValidationError
from space.lib import store
from space.lib.store.connection import DataclassInstance

SHORT_ID_LENGTH = 8
UUID_LENGTH = 36

TABLE_PREFIX = {
    "insights": "i",
    "decisions": "d",
    "tasks": "t",
    "spawns": "s",
    "replies": "r",
}
SINGULAR_TABLE = {
    "insight": "insights",
    "decision": "decisions",
    "task": "tasks",
    "spawn": "spawns",
    "reply": "replies",
}
PREFIX_TABLE = {v: k for k, v in TABLE_PREFIX.items()}
PREFIXES = {f"{p}/" for p in TABLE_PREFIX.values()}


def ref(table: str, id: str, length: int = SHORT_ID_LENGTH) -> str:
    table = SINGULAR_TABLE.get(table, table)
    id = strip_prefix(id)
    p = TABLE_PREFIX.get(table)
    return f"{p}/{id[:length]}" if p else id[:length]


def strip_prefix(ref: str) -> str:
    if len(ref) > 2 and ref[:2] in PREFIXES:
        return ref[2:]
    return ref


def validate_ref(ref: str) -> None:
    if not ref:
        raise ValidationError("Reference cannot be empty")


def _is_full_id(ref: str) -> bool:
    return len(ref) >= UUID_LENGTH


def _escape_like(ref: str) -> str:
    return ref.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def by_prefix[T: str](
    ref: str,
    table: str,
    id_column: str,
    id_type: Callable[[str], T],
    conn: sqlite3.Connection | None = None,
) -> T | None:
    row = row_by_prefix(ref, table, id_column, conn)
    return id_type(row[0]) if row else None


def row_by_prefix(
    ref: str,
    table: str,
    id_column: str,
    conn: sqlite3.Connection | None = None,
) -> sqlite3.Row | None:
    validate_ref(ref)

    def _query(c: sqlite3.Connection) -> sqlite3.Row | None:
        if _is_full_id(ref):
            return c.execute(
                f"SELECT * FROM {table} WHERE {id_column} = ?",  # noqa: S608
                (ref,),
            ).fetchone()

        if len(ref) >= SHORT_ID_LENGTH:
            like_ref = _escape_like(ref)
            matches = c.execute(
                f"SELECT * FROM {table} WHERE {id_column} LIKE ? ESCAPE '\\' LIMIT 2",  # noqa: S608
                (f"{like_ref}%",),
            ).fetchall()
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                exact = next((m for m in matches if m[0] == ref), None)
                if exact:
                    return exact
                sample = [m[0] for m in matches[:3]]
                raise ReferenceError(ref, 2, sample)
        return None

    if conn:
        return _query(conn)
    with store.ensure() as c:
        return _query(c)


def by_alt_key[T: str](
    ref: str,
    table: str,
    id_column: str,
    alt_column: str,
    id_type: Callable[[str], T],
    conn: sqlite3.Connection | None = None,
) -> T | None:
    row = row_by_alt_key(ref, table, id_column, alt_column, conn)
    return id_type(row[0]) if row else None


def row_by_alt_key(
    ref: str,
    table: str,
    id_column: str,
    alt_column: str,
    conn: sqlite3.Connection | None = None,
) -> sqlite3.Row | None:
    validate_ref(ref)

    def _query(c: sqlite3.Connection) -> sqlite3.Row | None:
        if _is_full_id(ref):
            return c.execute(
                f"SELECT * FROM {table} WHERE {id_column} = ?",  # noqa: S608
                (ref,),
            ).fetchone()

        row = c.execute(
            f"SELECT * FROM {table} WHERE {alt_column} = ?",  # noqa: S608
            (ref,),
        ).fetchone()
        if row:
            return row

        if len(ref) >= SHORT_ID_LENGTH:
            like_ref = _escape_like(ref)
            matches = c.execute(
                f"SELECT * FROM {table} WHERE {id_column} LIKE ? ESCAPE '\\' LIMIT 2",  # noqa: S608
                (f"{like_ref}%",),
            ).fetchall()
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                exact = next((m for m in matches if m[0] == ref), None)
                if exact:
                    return exact
                sample = [m[0] for m in matches[:3]]
                raise ReferenceError(ref, 2, sample)
        return None

    if conn:
        return _query(conn)
    with store.ensure() as c:
        return _query(c)


ALIASES: dict[str, str] = {
    "agents": "handle",
    "projects": "name",
}


def resolve[T: DataclassInstance](
    ref: str, table: str, model: type[T], *, include_merged: bool = False
) -> T:
    ref = strip_prefix(ref)
    alias = ALIASES.get(table)
    if alias:
        row = row_by_alt_key(ref, table, "id", alias)
    else:
        row = row_by_prefix(ref, table, "id")
    if row is None:
        raise NotFoundError(ref)
    result = store.from_row(row, model)
    if (
        table == "agents"
        and not include_merged
        and getattr(result, "merged_into", None) is not None
    ):
        raise NotFoundError(ref)
    return result


def resolve_short(ref: str) -> tuple[str, str]:
    """Parse ref like 'i/abc123' into ('insight', 'abc123-full-uuid').

    Returns (artifact_type, full_id).
    """
    if "/" not in ref:
        raise ValidationError(f"Invalid ref format: {ref} (expected x/id)")

    prefix, short_id = ref.split("/", 1)
    table = PREFIX_TABLE.get(prefix)
    if not table:
        raise ValidationError(f"Unknown prefix: {prefix}")

    artifact_type = SINGULAR_TABLE.get(table.removesuffix("s"), table)
    artifact_type = artifact_type.removesuffix("s")

    row = row_by_prefix(short_id, table, "id")
    if not row:
        raise NotFoundError(ref)

    return artifact_type, row["id"]
