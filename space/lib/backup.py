import argparse
import logging
import shutil
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from space.lib import config, paths, state
from space.lib.commands import echo, space_cmd

logger = logging.getLogger(__name__)


def _sqlite_backup(src_path: Path, dst_path: Path) -> None:
    src_conn = sqlite3.connect(src_path, timeout=30)
    dst_conn = sqlite3.connect(dst_path)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def _backup_data_snapshot(timestamp: str) -> dict[str, Any]:
    src = paths.dot_space()
    if not src.exists():
        return {}

    backup_path = paths.backups_dir() / "data" / timestamp
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.mkdir(parents=True, exist_ok=True)

    for db_file in sorted(src.glob("*.db")):
        if db_file.name.endswith(("-shm", "-wal")):
            continue
        dst_file = backup_path / db_file.name
        try:
            _sqlite_backup(db_file, dst_file)
        except sqlite3.Error as e:
            logger.error(f"Failed to backup {db_file.name}: {e}")
            if dst_file.exists():
                dst_file.unlink()

        for suffix in ["-shm", "-wal"]:
            wal_file = src / f"{db_file.stem}{suffix}"
            if wal_file.exists():
                shutil.copy2(wal_file, backup_path / wal_file.name)

    stats = _get_backup_stats(backup_path)

    for db_file in backup_path.glob("*.db"):
        try:
            conn = sqlite3.connect(str(db_file), timeout=2)
            try:
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    logger.error(f"Backup integrity check failed for {db_file.name}: {result}")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Failed to verify backup {db_file.name}: {e}")

    Path(backup_path).chmod(0o555)

    return stats


def _backup_spawns() -> dict[str, int]:
    src = paths.dot_space() / "spawns"
    backup_path = paths.backups_dir() / "spawns"

    if not src.exists():
        return {"total": 0, "new": 0}

    backup_path.parent.mkdir(parents=True, exist_ok=True)

    existing: set[Path] = set()
    if backup_path.exists():
        existing = {f.relative_to(backup_path) for f in backup_path.rglob("*") if f.is_file()}
        Path(backup_path).chmod(0o755)
        for item in backup_path.rglob("*"):
            Path(item).chmod(0o755 if item.is_dir() else 0o644)
        shutil.rmtree(backup_path)

    total = 0
    new = 0
    backup_path.mkdir()
    for item in src.iterdir():
        if item.is_file():
            shutil.copy2(item, backup_path / item.name)
            rel = Path(item.name)
            total += 1
            if rel not in existing:
                new += 1
        elif item.is_dir():
            dest_dir = backup_path / item.name
            shutil.copytree(item, dest_dir)
            for f in dest_dir.rglob("*"):
                if f.is_file():
                    total += 1
                    rel = f.relative_to(backup_path)
                    if rel not in existing:
                        new += 1

    Path(backup_path).chmod(0o555)

    return {"total": total, "new": new}


def _is_core_table(name: str) -> bool:
    return not ("_fts" in name or name.startswith("fts_"))


def _get_backup_stats(backup_path: Path) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for db_file in backup_path.glob("*.db"):
        try:
            db_file.chmod(0o644)
            conn = sqlite3.connect(str(db_file), timeout=2, check_same_thread=False)
            try:
                tables = [
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                    if _is_core_table(r[0])
                ]
                table_counts = {}
                total = 0
                for table in tables:
                    try:
                        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                        table_counts[table] = count
                        total += count
                    except sqlite3.OperationalError:
                        pass

                stats[db_file.name] = {
                    "tables": len(table_counts),
                    "rows": total,
                    "by_table": table_counts,
                }
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            stats[db_file.name] = {"tables": 0, "rows": 0, "by_table": {}}

    return stats


def _get_previous_backup() -> Path | None:
    data_dir = paths.backups_dir() / "data"
    if not data_dir.exists():
        return None
    snapshots = sorted(data_dir.iterdir(), reverse=True)
    return snapshots[0] if snapshots else None


def _calculate_row_delta(
    current_stats: dict[str, Any], previous_path: Path | None
) -> dict[str, Any]:
    if not previous_path or not previous_path.exists():
        return {db: {"total": None, "by_table": {}} for db in current_stats}

    previous_stats = _get_backup_stats(previous_path)
    deltas: dict[str, Any] = {}
    for db, info in current_stats.items():
        prev_info = previous_stats.get(db, {})
        prev_total = prev_info.get("rows", 0)
        prev_by_table = prev_info.get("by_table", {})

        table_deltas = {}
        for table, count in info.get("by_table", {}).items():
            delta = count - prev_by_table.get(table, 0)
            if delta != 0:
                table_deltas[table] = delta

        deltas[db] = {
            "total": info["rows"] - prev_total,
            "by_table": table_deltas,
        }
    return deltas


def _read_counter() -> int:
    return state.get("backup_counter", 0)


def _write_counter(n: int) -> None:
    state.set("backup_counter", n)


def on_spawn_complete() -> dict[str, Any] | None:
    cfg = config.load()
    threshold = cfg.backup.spawns_per_backup
    count = _read_counter() + 1
    if count >= threshold:
        _write_counter(0)
        return execute()
    _write_counter(count)
    return None


def _backup_tail(today: date, generate_fn=None) -> dict[str, Any]:
    tail_dir = paths.dot_space() / "tail"
    src = tail_dir / f"{today.isoformat()}.txt"

    if not src.exists() and generate_fn:
        lines = generate_fn(today)
        if not lines:
            return {"lines": 0}
        tail_dir.mkdir(parents=True, exist_ok=True)
        src.write_text("\n".join(lines))

    if not src.exists():
        return {"lines": 0}

    backup_dir = paths.backups_dir() / "tail"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / src.name

    shutil.copy2(src, dst)

    lines_count = src.read_text().count("\n") + 1 if src.stat().st_size > 0 else 0
    return {"lines": lines_count, "path": str(dst)}


def execute(generate_tail_fn=None) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    today = date.today()
    previous_backup = _get_previous_backup()
    data_stats = _backup_data_snapshot(timestamp)
    row_deltas = _calculate_row_delta(data_stats, previous_backup)
    spawns_stats = _backup_spawns()
    tail_stats = _backup_tail(today, generate_fn=generate_tail_fn)

    return {
        "timestamp": timestamp,
        "data_stats": data_stats,
        "row_deltas": row_deltas,
        "spawns_stats": spawns_stats,
        "tail_stats": tail_stats,
    }


def _format_delta(delta: int | None) -> str:
    if delta is None or delta == 0:
        return ""
    return f" (+{delta})" if delta > 0 else f" ({delta})"


def _format_table_deltas(by_table: dict[str, int]) -> str:
    if not by_table:
        return ""
    parts = [
        f"{t} {'+' if d > 0 else ''}{d}"
        for t, d in sorted(by_table.items(), key=lambda x: -abs(x[1]))
    ]
    return "\n    ".join(parts)


@space_cmd("backup")
def main(args: argparse.Namespace | None = None) -> None:
    """Backup space data."""
    if args is None:
        parser = argparse.ArgumentParser(description="Backup space data")
        if len(sys.argv) > 1 and sys.argv[1] == "backup":
            args = parser.parse_args(sys.argv[2:])
        else:
            args = parser.parse_args()

    result = execute()
    timestamp = result["timestamp"]
    data_stats = result["data_stats"]
    row_deltas = result["row_deltas"]
    spawns_stats = result["spawns_stats"]
    tail_stats = result.get("tail_stats", {})

    echo(f"~/.space_backups/data/{timestamp}")
    for db, info in data_stats.items():
        if "error" in info:
            echo(f"  {db}: {info['error']}")
        else:
            delta_info = row_deltas.get(db, {})
            total_delta = delta_info.get("total")
            table_deltas = delta_info.get("by_table", {})

            echo(f"  db: {info['rows']}{_format_delta(total_delta)}")
            if table_deltas:
                echo(f"    {_format_table_deltas(table_deltas)}")

    total = spawns_stats.get("total", 0)
    new = spawns_stats.get("new", 0)
    echo(f"  jsonl: {total}{_format_delta(new)}")

    tail_lines = tail_stats.get("lines", 0)
    if tail_lines > 0:
        echo(f"  tail: {tail_lines} lines")
