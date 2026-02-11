import logging
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Sized
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


class SpaceConnection(sqlite3.Connection):
    """Subclass to allow weak references."""


logger = logging.getLogger(__name__)

CONN_SLOW_SECS = 0.1
CHECKPOINT_SECS = 60.0
_checkpoint_lock = threading.Lock()
_last_checkpoint: dict[str, float] = {}


def connect(db_path: Path) -> sqlite3.Connection:
    """Connect to SQLite with write contention monitoring.

    Uses WAL mode + 5s timeout for concurrent writes.
    SQLite write ceiling: ~1000 writes/sec on SSD.
    """
    start = time.perf_counter()

    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5.0, factory=SpaceConnection)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    elapsed = time.perf_counter() - start
    if elapsed > CONN_SLOW_SECS:
        logger.warning(f"SQLite connection took {elapsed:.3f}s (possible lock contention)")

    return conn


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Connect to SQLite in read-only mode without mutating DB files.

    Uses SQLite URI mode=ro to prevent implicit database creation and to avoid
    PRAGMAs that may write (e.g. journal_mode changes).
    """
    start = time.perf_counter()

    conn = sqlite3.connect(
        f"file:{db_path}?mode=ro", uri=True, check_same_thread=False, factory=SpaceConnection
    )
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None

    conn.execute("PRAGMA foreign_keys = ON")

    elapsed = time.perf_counter() - start
    if elapsed > CONN_SLOW_SECS:
        logger.warning(f"SQLite connection took {elapsed:.3f}s (possible lock contention)")

    return conn


def checkpoint_wal(db_dir: Path) -> None:
    """Merge WAL data into main DB files for backup/transfer.

    Args:
        db_dir: Directory containing *.db files
    """
    for db_file in sorted(db_dir.glob("*.db")):
        try:
            conn = connect(db_file)
            conn.execute("PRAGMA wal_checkpoint(RESTART)")
            conn.close()

        except sqlite3.DatabaseError as e:
            logger.warning(f"Failed to checkpoint {db_file.name}: {e}")


def maybe_checkpoint(conn: sqlite3.Connection) -> None:
    """Periodically checkpoint WAL to keep it from growing unbounded."""
    row = conn.execute("PRAGMA database_list").fetchone()
    if not row or not row[2]:
        return

    db_path = str(Path(row[2]))
    now = time.monotonic()

    with _checkpoint_lock:
        last = _last_checkpoint.get(db_path, 0.0)
        if now - last < CHECKPOINT_SECS:
            return
        _last_checkpoint[db_path] = now

    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.DatabaseError as e:
        logger.warning(f"WAL checkpoint failed: {e}")


def placeholders(items: Sized) -> str:
    """Generate SQL placeholder string for IN clauses."""
    return ",".join("?" * len(items))


def fts_tokenize(text: str) -> list[str]:
    """Extract searchable tokens from text."""
    return re.findall(r"[a-z0-9]+", text.lower())


def fts_query_string(terms: list[str]) -> str:
    """Build FTS MATCH query from tokens."""
    return " OR ".join(f"{term}*" for term in terms)


def fts_search(
    conn: sqlite3.Connection,
    query: str,
    fts_executor: Callable[[sqlite3.Connection, str], list[T]],
    fallback_executor: Callable[[sqlite3.Connection, str], list[T]],
) -> list[T]:
    """Execute FTS search with automatic fallback on SQLite errors.

    Args:
        conn: Database connection
        query: Raw search query from user
        fts_executor: Function that runs FTS query, receives (conn, fts_match_string)
        fallback_executor: Function that runs LIKE fallback, receives (conn, original_query)
    """
    terms = fts_tokenize(query)
    if not terms:
        return fallback_executor(conn, query)

    fts_match = fts_query_string(terms)
    try:
        return fts_executor(conn, fts_match)
    except sqlite3.OperationalError:
        return fallback_executor(conn, query)
