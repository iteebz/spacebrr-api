import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from space.lib import paths


def _is_test() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("SPACE_ENV") == "test"


def _cutoff_ts(days: int, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return (now - timedelta(days=days)).isoformat()


def capture(
    command: str,
    args: dict[str, Any] | None,
    exit_code: int,
    duration_ms: int,
) -> None:
    if _is_test():
        return

    spawn_id = paths.spawn_id()
    ts = datetime.now(UTC).isoformat()
    args_json = json.dumps(args) if args else None

    db_path = paths.dot_space() / "space.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO cli_invocations (ts, spawn_id, command, args, exit_code, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts, spawn_id, command, args_json, exit_code, duration_ms),
        )
        conn.commit()
    finally:
        conn.close()


def usage_stats(days: int = 30) -> dict[str, Any]:
    db_path = paths.dot_space() / "space.db"
    conn = sqlite3.connect(db_path)
    try:
        cutoff = _cutoff_ts(days)

        total = conn.execute(
            "SELECT COUNT(*) FROM cli_invocations WHERE ts > ?", (cutoff,)
        ).fetchone()[0]

        by_command = conn.execute(
            """
            SELECT command,
                   COUNT(*) as total,
                   SUM(CASE WHEN exit_code != 0 THEN 1 ELSE 0 END) as failures
            FROM cli_invocations
            WHERE ts > ?
            GROUP BY command
            ORDER BY total DESC
            """,
            (cutoff,),
        ).fetchall()

        return {
            "days": days,
            "total": total,
            "by_command": [
                {"command": cmd, "total": tot, "failures": fail} for cmd, tot, fail in by_command
            ],
        }
    finally:
        conn.close()


def used_commands(days: int = 30) -> set[str]:
    db_path = paths.dot_space() / "space.db"
    conn = sqlite3.connect(db_path)
    try:
        cutoff = _cutoff_ts(days)
        rows = conn.execute(
            "SELECT DISTINCT command FROM cli_invocations WHERE ts > ?",
            (cutoff,),
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def failures(days: int = 7) -> list[dict[str, Any]]:
    db_path = paths.dot_space() / "space.db"
    conn = sqlite3.connect(db_path)
    try:
        cutoff = _cutoff_ts(days)

        rows = conn.execute(
            """
            SELECT ts, spawn_id, command, args, exit_code
            FROM cli_invocations
            WHERE exit_code != 0 AND ts > ?
            ORDER BY ts DESC
            LIMIT 50
            """,
            (cutoff,),
        ).fetchall()

        return [
            {
                "ts": ts,
                "spawn_id": spawn_id,
                "command": cmd,
                "args": json.loads(args) if args else None,
                "exit_code": exit_code,
            }
            for ts, spawn_id, cmd, args, exit_code in rows
        ]
    finally:
        conn.close()
