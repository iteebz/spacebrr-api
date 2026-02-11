import argparse
import json
import logging
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from space import stats
from space.lib import paths, store
from space.lib.commands import echo, fail, space_cmd
from space.lib.display import format as fmt
from space.lib.store import migrations

logger = logging.getLogger(__name__)

INTERNAL_TABLES = frozenset({"_migrations"})


class PrimitiveCount(TypedDict):
    active: int
    archived: int


class IntegrityResult(TypedDict):
    ok: bool
    issues: list[str]
    counts: dict[str, int]
    fk_violations: dict[str, int]
    total_rows: int
    primitives: dict[str, PrimitiveCount]
    schema_drift: list[str]


ColumnInfo = tuple[str, str, bool, bool]


def check_backup_has_data(backup_path: Path, db_name: str, min_rows: int = 1) -> bool:
    db_file = backup_path / db_name
    if not db_file.exists():
        return False

    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != '_migrations'"
        )
        tables = [row[0] for row in cursor.fetchall()]

        if not tables:
            return False

        total_rows = 0
        for table in tables:
            sql = f"SELECT COUNT(*) FROM {table}"  # noqa: S608
            result = conn.execute(sql).fetchone()
            count = result[0] if result else 0
            total_rows += count

        return not total_rows < min_rows

    except sqlite3.DatabaseError as e:
        logger.error(f"Backup {backup_path.name}/{db_name}: corrupted - {e}")
        return False
    finally:
        if conn:
            conn.close()


def get_backup_stats(backup_path: Path, db_name: str) -> dict[str, int]:
    db_file = backup_path / db_name
    if not db_file.exists():
        return {}

    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != '_migrations'"
        )
        tables = [row[0] for row in cursor.fetchall()]

        stats_dict = {}
        for table in tables:
            sql = f"SELECT COUNT(*) FROM {table}"  # noqa: S608
            result = conn.execute(sql).fetchone()
            stats_dict[table] = result[0] if result else 0

        return stats_dict

    except sqlite3.DatabaseError:
        return {}
    finally:
        if conn:
            conn.close()


def compare_snapshots(
    before: dict[str, int], after: dict[str, int], threshold: float = 0.8
) -> list[str]:
    warnings = []

    for db_name, before_count in before.items():
        after_count = after.get(db_name, 0)
        if before_count == 0:
            continue

        if after_count == 0:
            warnings.append(f"{db_name}: completely emptied ({before_count} → 0 rows)")
        else:
            loss_pct = (before_count - after_count) / before_count
            if loss_pct > threshold:
                warnings.append(
                    f"{db_name}: {loss_pct * 100:.0f}% data loss ({before_count} → {after_count} rows)"
                )

    return warnings


FTS_TABLES = ("spawns_fts", "decisions_fts", "insights_fts", "tasks_fts", "replies_fts")


def check_fts_integrity(conn: sqlite3.Connection) -> list[str]:
    corrupted = []
    for table in FTS_TABLES:
        try:
            conn.execute(f"SELECT * FROM {table} LIMIT 1")  # noqa: S608
        except sqlite3.DatabaseError:
            corrupted.append(table)
    return corrupted


def rebuild_fts(conn: sqlite3.Connection, table: str) -> bool:
    if table not in FTS_TABLES:
        return False
    try:
        conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
        logger.info(f"Rebuilt FTS5 index: {table}")
        return True
    except sqlite3.DatabaseError as e:
        logger.error(f"Failed to rebuild {table}: {e}")
        return False


def repair_fts_if_needed(conn: sqlite3.Connection) -> list[str]:
    corrupted = check_fts_integrity(conn)
    return [table for table in corrupted if rebuild_fts(conn, table)]


def get_core_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return sorted(name for (name,) in rows if not ("_fts" in name or name in INTERNAL_TABLES))


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def count_table(conn: sqlite3.Connection, table: str, active_only: bool = False) -> int:
    if not active_only:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    if has_column(conn, table, "archived_at"):
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE archived_at IS NULL").fetchone()[0]  # noqa: S608
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


def check_fk_violations(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    violations: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        violations[(row["table"], row["parent"])] += 1
    return dict(violations)


def sqlite_integrity_check(conn: sqlite3.Connection) -> str | None:
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    return None if result == "ok" else result


def check_integrity(*, repair_fks: bool = False) -> IntegrityResult:
    if not store.database_exists():
        return {
            "ok": False,
            "issues": [f"{DB_NAME} missing"],
            "counts": {},
            "fk_violations": {},
            "total_rows": 0,
            "primitives": {},
            "schema_drift": [],
        }

    with store.existing() as conn:
        return check_database_integrity(conn, repair_fks=repair_fks)


def repair_missing_agents(conn: sqlite3.Connection) -> int:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    orphan_agent_ids: set[str] = set()

    fk_cache: dict[tuple[str, int], str] = {}

    for row in rows:
        if row["parent"] != "agents":
            continue
        table = row["table"]
        rowid = row["rowid"]
        fkid = row["fkid"]

        if (table, fkid) not in fk_cache:
            fk_list = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            for fk in fk_list:
                if fk["id"] == fkid:
                    fk_cache[(table, fkid)] = fk["from"]
                    break

        col = fk_cache.get((table, fkid))
        if not col:
            continue

        agent_row = conn.execute(f"SELECT {col} FROM {table} WHERE rowid = ?", (rowid,)).fetchone()  # noqa: S608
        if agent_row and agent_row[0]:
            orphan_agent_ids.add(agent_row[0])

    if not orphan_agent_ids:
        return 0

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    created = 0
    for agent_id in sorted(orphan_agent_ids):
        identity = f"orphan-{agent_id[:8]}"
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO agents (id, identity, type, created_at)
            VALUES (?, ?, "ai", ?)
            """,
            (agent_id, identity, now),
        )
        created += cur.rowcount or 0

    return created


def extract_schema(conn: sqlite3.Connection) -> dict[str, Any]:
    schema: dict[str, Any] = {"tables": {}, "indexes": set(), "triggers": set()}

    fts_internal = ("_data", "_idx", "_content", "_docsize", "_config")

    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall():
        if name == "_migrations" or any(name.endswith(s) for s in fts_internal):
            continue
        escaped = name.replace("'", "''")
        cols: list[ColumnInfo] = [
            (r[1], (r[2] or "").upper(), bool(r[3]), bool(r[5]))
            for r in conn.execute(f"PRAGMA table_info('{escaped}')").fetchall()
        ]
        schema["tables"][name] = cols

    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
    ).fetchall():
        schema["indexes"].add(name)

    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        schema["triggers"].add(name)

    return schema


def build_expected_schema() -> dict[str, Any] | None:
    mem_conn = sqlite3.connect(":memory:")
    try:
        mem_conn.executescript(migrations.schema_sql())
        return extract_schema(mem_conn)
    finally:
        mem_conn.close()


def check_schema_drift(conn: sqlite3.Connection) -> list[str]:
    expected = build_expected_schema()
    if not expected:
        return ["no migrations found"]

    live = extract_schema(conn)
    drift: list[str] = []

    for table, expected_cols in expected["tables"].items():
        if table not in live["tables"]:
            drift.append(f"missing table: {table}")
            continue
        live_cols = live["tables"][table]
        expected_set = set(expected_cols)
        live_set = set(live_cols)
        for col in expected_set - live_set:
            name, _typ, _notnull, _pk = col
            if any(c[0] == name for c in live_set):
                drift.append(f"{table}.{name}: schema mismatch")
            else:
                drift.append(f"{table}.{name}: missing column")
        for col in live_set - expected_set:
            name = col[0]
            if not any(c[0] == name for c in expected_set):
                drift.append(f"{table}.{name}: extra column")

    drift.extend(f"extra table: {t}" for t in live["tables"] if t not in expected["tables"])
    drift.extend(f"missing index: {i}" for i in expected["indexes"] - live["indexes"])
    drift.extend(f"missing trigger: {t}" for t in expected["triggers"] - live["triggers"])

    return drift


def check_database_integrity(
    conn: sqlite3.Connection, *, repair_fks: bool = False
) -> IntegrityResult:
    result: IntegrityResult = {
        "ok": True,
        "issues": [],
        "counts": {},
        "fk_violations": {},
        "total_rows": 0,
        "primitives": {},
        "schema_drift": [],
    }

    try:
        if repair_fks:
            repair_missing_agents(conn)

        core_tables = get_core_tables(conn)

        integrity_error = sqlite_integrity_check(conn)
        if integrity_error:
            result["ok"] = False
            result["issues"].append(f"integrity: {integrity_error}")

        fk_violations = check_fk_violations(conn)
        if fk_violations:
            result["ok"] = False
            result["fk_violations"] = {f"{t}→{p}": n for (t, p), n in fk_violations.items()}

        for table in core_tables:
            count = count_table(conn, table)
            result["counts"][table] = count
            result["total_rows"] += count
            active = count_table(conn, table, active_only=True)
            result["primitives"][table] = {"active": active, "archived": count - active}

        drift = check_schema_drift(conn)
        if drift:
            result["ok"] = False
            result["schema_drift"] = drift

    except sqlite3.Error as exc:
        result["ok"] = False
        result["issues"].append(str(exc))

    return result


DB_NAME = "space.db"


def backup_age() -> int | None:
    data_dir = paths.backups_dir() / "data"
    if not data_dir.exists():
        return None
    snapshots = sorted(data_dir.iterdir(), reverse=True)
    if not snapshots:
        return None
    try:
        ts = datetime.strptime(snapshots[0].name, "%Y%m%d_%H%M%S")
        return int((datetime.now() - ts).total_seconds())
    except ValueError:
        return None


def get_summary(*, repair_fks: bool = False) -> dict[str, Any]:
    if not store.database_exists():
        return {
            "ok": False,
            "issues": [f"{DB_NAME} missing"],
            "counts": {},
            "fk_violations": {},
            "total_rows": 0,
            "primitives": {},
            "schema_drift": [],
        }

    with store.existing() as conn:
        integrity = check_database_integrity(conn, repair_fks=repair_fks)

    return {
        "ok": integrity["ok"],
        "total_rows": integrity["total_rows"],
        "backup_age_seconds": backup_age(),
        "primitives": integrity["primitives"],
        "fk_violations": integrity["fk_violations"],
        "issues": integrity["issues"],
        "counts": integrity["counts"],
        "schema_drift": integrity["schema_drift"],
    }


def _render_health(*, repair_fks: bool = False, json_output: bool = False) -> None:
    summary = get_summary(repair_fks=repair_fks)

    if json_output:
        echo(json.dumps(summary, indent=2))
        if not summary["ok"]:
            fail("health check failed")
        return

    b_age = fmt.age_seconds(summary["backup_age_seconds"])
    status = "ok" if summary["ok"] else "error"
    echo(f"{status}: {summary['total_rows']} rows across {len(summary['primitives'])} tables")
    echo(f"backup: {b_age} ago")

    if not summary["fk_violations"]:
        echo("no FK violations")
    if not summary.get("schema_drift"):
        echo("no schema drift")

    integrity_error = summary["issues"][:1]
    if not integrity_error:
        echo("integrity check passed")

    echo("\n[PRIMITIVES]")
    sorted_primitives = sorted(
        summary["primitives"].items(), key=lambda x: x[1]["active"], reverse=True
    )
    for table, counts in sorted_primitives:
        archived = counts["archived"]
        suffix = f" (+{archived})" if archived else ""
        echo(f"  {table}: {counts['active']}{suffix}")

    if summary["fk_violations"]:
        echo("\n[FK VIOLATIONS]")
        for rel, count in summary["fk_violations"].items():
            echo(f"  {rel}: {count} rows")

    if summary.get("schema_drift"):
        echo("\n[SCHEMA DRIFT]")
        for drift in summary["schema_drift"]:
            echo(f"  {drift}")

    if summary["issues"]:
        echo("\n[ISSUES]")
        for issue in summary["issues"]:
            echo(f"  {issue}")
        fail("health check failed")


def _render_code(*, show_trend: bool = False, json_output: bool = False) -> None:
    result = stats.code.ci()

    if json_output:
        data: dict[str, Any] = dict(result)
        if show_trend:
            data["trend"] = stats.code.trend()
        echo(json.dumps(data, indent=2))
        if not result["ok"]:
            fail("code health check failed")
        return

    status = "ok" if result["ok"] else "error"
    echo(f"\n{status} code health: {result['score']}/100")

    lint_r = result["lint"]
    lint_status = "ok" if lint_r["ok"] else "error"
    echo(f"  {lint_status} lint: {lint_r['violations']} violations")

    type_r = result["typecheck"]
    type_status = "ok" if type_r["ok"] else "error"
    suppressions = result.get("suppressions", 0)
    supp_msg = f" ({suppressions} suppressions)" if suppressions else ""
    echo(f"  {type_status} types: {type_r['errors']} errors{supp_msg}")

    test_r = result["tests"]
    test_status = "ok" if test_r["ok"] else "error"
    echo(f"  {test_status} tests: {test_r['passed']} passed, {test_r['failed']} failed")

    arch_r = result["architecture"]
    arch_status = "ok" if arch_r["ok"] else "error"
    echo(f"  {arch_status} architecture: {len(arch_r['violations'])} violations")

    echo(f"  stashes: {result['stashes']}")

    if show_trend:
        history = stats.code.trend(limit=5)
        if history:
            echo("\n[TREND]")
            for entry in history:
                echo(f"  {entry['created_at'][:16]} score={entry['score']}")

    if not result["ok"]:
        fail("code health check failed")


@space_cmd("health")
def main() -> None:
    """Database and code health checks."""
    parser = argparse.ArgumentParser(prog="health", description="Database and code health checks")
    parser.add_argument("--repair-fks", action="store_true", help="Repair FK violations")
    parser.add_argument("-c", "--code", action="store_true", help="Include code health")
    parser.add_argument("-t", "--trend", action="store_true", help="Show health score history")
    parser.add_argument("-j", "--json", action="store_true", dest="json_output", help="Output JSON")

    args = parser.parse_args()

    _render_health(repair_fks=args.repair_fks, json_output=args.json_output)
    if args.code:
        _render_code(show_trend=args.trend, json_output=args.json_output)
