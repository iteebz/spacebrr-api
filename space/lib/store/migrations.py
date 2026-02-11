import inspect
import logging
import shutil
import sqlite3
from collections.abc import Callable, Sequence
from datetime import datetime
from importlib import import_module
from pathlib import Path

from space.core.errors import ValidationError
from space.lib.store.sqlite import checkpoint_wal, connect

logger = logging.getLogger(__name__)

MigrationFn = Callable[[sqlite3.Connection], None]
Migration = tuple[str, str | MigrationFn]

_schema_sql_cache: str | None = None


def _schema_path() -> Path:
    return Path(__file__).parent.parent.parent / "core" / "schema.sql"


def schema_sql() -> str:
    global _schema_sql_cache
    if _schema_sql_cache is None:
        _schema_sql_cache = _schema_path().read_text()
    return _schema_sql_cache


def _get_db_path(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    if row and row[2]:
        return Path(row[2])
    return None


def _create_backup(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_suffix(f".{timestamp}.backup")
    try:
        src_conn = sqlite3.connect(db_path, timeout=30)
        dst_conn = sqlite3.connect(backup_path)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()
        return backup_path
    except Exception:
        if backup_path.exists():
            backup_path.unlink()
        raise


def _restore_backup(backup_path: Path, db_path: Path) -> None:
    checkpoint_wal(db_path.parent)
    shutil.copy2(backup_path, db_path)
    logger.warning(f"Restored database from backup: {backup_path}")


def _is_fresh(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name != '_migrations'"
    ).fetchone()
    return row[0] == 0


def get(module_path: str) -> list[Migration]:
    parts = module_path.split(".")
    module_dir = Path(__file__).parent.parent.parent
    for part in parts[1:]:
        module_dir = module_dir / part
    migrations_dir = module_dir / "migrations"

    if not migrations_dir.exists():
        return []

    migrations: list[Migration] = [
        (sql_file.stem, sql_file.read_text()) for sql_file in sorted(migrations_dir.glob("*.sql"))
    ]

    try:
        mig_module = import_module(f"{module_path}.migrations")
    except (ImportError, AttributeError):
        mig_module = None

    if mig_module:
        for name, obj in inspect.getmembers(mig_module):
            if name.startswith("migration_") and callable(obj):
                mig_name = name.replace("migration_", "")
                if not any(m[0] == mig_name for m in migrations):
                    migrations.append((mig_name, obj))  # type: ignore[arg-type]

    return sorted(migrations, key=lambda x: x[0])


def ensure_schema(
    db_path: Path,
    migs: Sequence[Migration] | None = None,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY)")
        conn.commit()

        if migs:
            migrate(conn, migs)
        elif _is_fresh(conn):
            conn.executescript(schema_sql())
            conn.commit()
        else:
            pass

        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection, migs: Sequence[Migration]) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY)")
    conn.commit()

    applied_rows = conn.execute("SELECT name FROM _migrations").fetchall()
    applied = {row[0] for row in applied_rows}
    pending = [(name, migration) for name, migration in migs if name not in applied]
    if not pending:
        return

    db_path = _get_db_path(conn)
    backup_path: Path | None = None

    try:
        for name, migration in pending:
            if db_path and db_path.exists() and not backup_path:
                backup_path = _create_backup(db_path)

            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name != '_migrations' AND name != 'sqlite_sequence' AND name NOT LIKE '%_fts%'"
                )
                tables = [row[0] for row in cursor.fetchall()]
                before = {t: _get_table_count(conn, t) for t in tables}

                if callable(migration):
                    migration(conn)
                else:
                    conn.executescript(migration)

                for table, count_before in before.items():
                    try:
                        _check_migration_safety(conn, table, count_before, allow_loss=0)
                    except ValueError as e:
                        logger.error(f"Migration '{name}' data loss detected: {e}")
                        raise

                conn.execute("INSERT OR IGNORE INTO _migrations (name) VALUES (?)", (name,))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Migration '{name}' failed: {e}")
                if backup_path and db_path:
                    _restore_backup(backup_path, db_path)
                    logger.error(f"Restored database from backup: {backup_path}")
                raise
    finally:
        if backup_path and backup_path.exists():
            backup_path.unlink()


def _get_table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if not cursor.fetchone()[0]:
            return 0
        sql = f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608
        result = conn.execute(sql).fetchone()
        return result[0] if result else 0
    except sqlite3.OperationalError:
        return 0


def _check_migration_safety(
    conn: sqlite3.Connection, table: str, before: int, allow_loss: int = 0
) -> None:
    after = _get_table_count(conn, table)
    lost = before - after

    if lost > allow_loss:
        msg = f"Migration {table}: {lost} rows lost (before: {before}, after: {after})"
        logger.error(msg)
        raise ValidationError(msg)

    if lost > 0:
        logger.warning(
            f"Migration {table}: {lost} rows removed (expected for allow_loss={allow_loss})"
        )
