import contextvars
import json
import sqlite3
import threading
import weakref
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import fields
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol, get_args, get_origin

from space.lib import paths
from space.lib.store import migrations
from space.lib.store.sqlite import connect, connect_readonly, maybe_checkpoint

Row = sqlite3.Row

_DB_FILE = "space.db"
_local = threading.local()

# Global registry to allow closing connections across all threads in tests
_all_connections: weakref.WeakSet[sqlite3.Connection] = weakref.WeakSet()
_all_connections_lock = threading.Lock()

_db_path_override: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "db_path_override", default=None
)


def _in_transaction(conn: sqlite3.Connection) -> bool:
    in_tx = getattr(conn, "in_transaction", False)
    return in_tx if isinstance(in_tx, bool) else False


def _get_cache() -> dict[str, Any]:
    if not hasattr(_local, "connections"):
        _local.connections = {}
        _local.migrations_loaded = set()
    return _local.connections


def _get_migrations_loaded() -> set[str]:
    if not hasattr(_local, "migrations_loaded"):
        _local.connections = {}
        _local.migrations_loaded = set()
    return _local.migrations_loaded


def database_exists() -> bool:
    return (paths.dot_space() / _DB_FILE).exists()


class DataclassInstance(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]


def _coerce_value(value: Any, field_type: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(field_type)
    if origin is not None:
        args = get_args(field_type)
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            field_type = non_none[0]
            origin = get_origin(field_type)
    if isinstance(field_type, type) and issubclass(field_type, Enum):
        return field_type(value)
    if field_type is bool:
        return bool(value)
    if origin is list and isinstance(value, str):
        return json.loads(value)
    return value


def from_row[T: DataclassInstance](row: dict[str, Any] | Any, dataclass_type: type[T]) -> T:
    row_dict: dict[str, Any] = dict(row) if not isinstance(row, dict) else row
    field_info = {f.name: f.type for f in fields(dataclass_type)}
    kwargs: dict[str, Any] = {}
    for name, ftype in field_info.items():
        if name in row_dict:
            kwargs[name] = _coerce_value(row_dict[name], ftype)
    return dataclass_type(**kwargs)


class _ConnContext:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        return False


def resolve_db_path() -> Path:
    override = _db_path_override.get()
    return (override / _DB_FILE) if override else (paths.dot_space() / _DB_FILE)


def ensure() -> _ConnContext:
    """Thread-local cached connection. Use store.transaction() for atomicity."""
    db_path = resolve_db_path()
    cache_key = str(db_path)

    cache = _get_cache()
    if cache_key in cache:
        return _ConnContext(cache[cache_key])

    db_path.parent.mkdir(parents=True, exist_ok=True)

    migrations_loaded = _get_migrations_loaded()
    if cache_key not in migrations_loaded:
        migrations.ensure_schema(db_path)
        migrations_loaded.add(cache_key)

    conn = connect(db_path)
    cache[cache_key] = conn
    with _all_connections_lock:
        _all_connections.add(conn)
    return _ConnContext(conn)


@contextmanager
def existing() -> Generator[sqlite3.Connection, None, None]:
    """Open a connection to an existing DB without running migrations.

    Use this for diagnostics/health checks that must not mutate state.
    """
    db_path = resolve_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"database does not exist: {db_path}")

    conn = connect_readonly(db_path)
    try:
        yield conn
    finally:
        with suppress(sqlite3.ProgrammingError):
            conn.close()


@contextmanager
def write() -> Generator[sqlite3.Connection, None, None]:
    with transaction() as conn:
        yield conn


def close_all() -> None:
    # 1. Clear current thread's cache
    cache = _get_cache()
    for conn in cache.values():
        with suppress(sqlite3.ProgrammingError):
            conn.close()
    cache.clear()

    # 2. Close all connections in the global registry (for tests)
    with _all_connections_lock:
        for conn in _all_connections:
            with suppress(sqlite3.ProgrammingError):
                conn.close()
        _all_connections.clear()


@contextmanager
def transaction() -> Generator[sqlite3.Connection, None, None]:
    """Execute multiple statements atomically.

    Usage:
        with store.transaction() as conn:
            conn.execute("INSERT ...")
            conn.execute("UPDATE ...")
        # auto-commits on exit, rollbacks on exception
    """
    with ensure() as conn:
        if _in_transaction(conn):
            if not hasattr(_local, "savepoint_seq"):
                _local.savepoint_seq = 0
            _local.savepoint_seq += 1
            savepoint = f"sp_{_local.savepoint_seq}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                yield conn
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            return

        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if _in_transaction(conn):
                conn.execute("COMMIT")
                maybe_checkpoint(conn)
        except Exception:
            if _in_transaction(conn):
                conn.execute("ROLLBACK")
            raise


def set_test_db_path(db_dir: Path | None) -> None:
    """Set database path override for test isolation."""
    _db_path_override.set(db_dir)


def _reset_for_testing() -> None:  # pyright: ignore[reportUnusedFunction]
    _db_path_override.set(None)
    close_all()
    _get_migrations_loaded().clear()


ARCHIVABLE_TABLES = {"agents", "projects", "decisions", "insights"}


def unarchive(table: str, id: str, conn: sqlite3.Connection | None = None) -> bool:
    """Unarchive entity if archived. Returns True if state changed."""
    if table not in ARCHIVABLE_TABLES:
        raise ValueError(f"Table '{table}' is not archivable")

    def do_update(c: sqlite3.Connection) -> int:
        cursor = c.execute(
            f"UPDATE {table} SET archived_at = NULL WHERE id = ? AND archived_at IS NOT NULL",  # noqa: S608
            (id,),
        )
        return cursor.rowcount

    if conn:
        return do_update(conn) > 0
    with write() as c:
        return do_update(c) > 0
