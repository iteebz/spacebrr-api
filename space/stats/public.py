
import contextlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from space.lib import config, store

from .swarm import absence_metrics


def _git_commits_since(repo: Path, since: str) -> int:
    """Count commits since date."""
    git_path = shutil.which("git")
    if not git_path:
        return 0
    try:
        result = subprocess.run(
            [git_path, "log", "--oneline", f"--since={since}"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return 0
        return len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
    except Exception:
        return 0


def _code_lines(repo: Path) -> int:
    """Count Python lines in space module."""
    space_dir = repo / "space"
    if not space_dir.exists():
        return 0
    total = 0
    for py in space_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            with contextlib.suppress(Exception):
                total += len(py.read_text().splitlines())
    return total


def _test_lines(repo: Path) -> int:
    """Count test lines."""
    tests_dir = repo / "tests"
    if not tests_dir.exists():
        return 0
    total = 0
    for py in tests_dir.rglob("*.py"):
        if "__pycache__" not in str(py):
            with contextlib.suppress(Exception):
                total += len(py.read_text().splitlines())
    return total


def _findings_count(stats_path: str | None) -> int:
    """Count research findings from website repo."""
    if not stats_path:
        return 0
    website_root = Path(stats_path).expanduser().parent.parent
    findings_dir = website_root / "docs" / "findings"
    if not findings_dir.exists():
        return 0
    return len(list(findings_dir.glob("*.md")))


def get() -> dict[str, Any]:
    """Minimal public stats. No sensitive data."""
    with store.ensure() as conn:
        spawns_24h = conn.execute(
            "SELECT COUNT(*) FROM spawns WHERE created_at > datetime('now', '-24 hours')"
        ).fetchone()[0]

        spawns_7d = conn.execute(
            "SELECT COUNT(*) FROM spawns WHERE created_at > datetime('now', '-7 days')"
        ).fetchone()[0]

        total_spawns = conn.execute("SELECT COUNT(*) FROM spawns").fetchone()[0]

        total_decisions = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE deleted_at IS NULL"
        ).fetchone()[0]

        open_q = conn.execute(
            "SELECT COUNT(*) FROM insights WHERE open = 1 AND deleted_at IS NULL AND archived_at IS NULL"
        ).fetchone()[0]

        total_insights = conn.execute(
            "SELECT COUNT(*) FROM insights WHERE deleted_at IS NULL AND archived_at IS NULL"
        ).fetchone()[0]

        agent_count = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE type = 'ai' AND archived_at IS NULL AND deleted_at IS NULL"
        ).fetchone()[0]

        total_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE deleted_at IS NULL"
        ).fetchone()[0]

        total_replies = conn.execute(
            "SELECT COUNT(*) FROM replies WHERE deleted_at IS NULL"
        ).fetchone()[0]

        days_active = conn.execute(
            "SELECT COUNT(DISTINCT date(created_at)) FROM spawns"
        ).fetchone()[0]

    repo = Path(__file__).parent.parent.parent.parent
    commits = _git_commits_since(repo, "2025-01-01")
    code_loc = _code_lines(repo)
    test_loc = _test_lines(repo)

    cfg = config.load()
    findings = _findings_count(cfg.stats_json_path)

    absence = absence_metrics(hours=168)

    return {
        "spawns_24h": spawns_24h,
        "spawns_7d": spawns_7d,
        "total_spawns": total_spawns,
        "decisions": total_decisions,
        "open_questions": open_q,
        "insights": total_insights,
        "agents": agent_count,
        "tasks": total_tasks,
        "replies": total_replies,
        "days_active": days_active,
        "commits": commits,
        "code_loc": code_loc,
        "test_loc": test_loc,
        "findings": findings,
        "absence_autonomy": absence["completion_autonomy"],
        "absence_io_ratio": absence["input_output_ratio"],
    }


def write(path: str | None = None) -> str:
    """Write public stats to JSON file for website consumption."""
    if path is None:
        cfg = config.load()
        path = cfg.stats_json_path
    if not path:
        return ""

    stats = get()
    stats["updated_at"] = datetime.now(UTC).isoformat()

    dest = Path(path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(stats, indent=2))
    return str(dest)
