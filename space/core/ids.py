"""Collision-free short ID generation."""

import sqlite3
from uuid import uuid4

from space.lib import store

VALID_TABLES = {
    "insights",
    "decisions",
    "tasks",
    "replies",
    "spawns",
    "agents",
    "projects",
}


def generate(table: str, conn: sqlite3.Connection | None = None) -> str:
    """Generate 8-char collision-free ID for table.

    Retries up to 10 times if collision detected.
    8 hex chars = 4B namespace per table.
    At 10k records, collision probability ~0.0002%.
    """
    if table not in VALID_TABLES:
        raise ValueError(f"Invalid table: {table}")

    def _gen(c: sqlite3.Connection) -> str:
        for _ in range(10):
            candidate = uuid4().hex[:8]
            query = f"SELECT 1 FROM {table} WHERE id LIKE ? LIMIT 1"  # noqa: S608
            clash = c.execute(query, (f"{candidate}%",)).fetchone()
            if not clash:
                return candidate
        raise RuntimeError(f"ID generation exhausted for {table}")

    if conn:
        return _gen(conn)
    with store.ensure() as c:
        return _gen(c)
