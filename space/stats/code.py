import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from space.lib import store


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(cwd) if cwd else None,
        )
        return result.returncode, result.stdout, result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return -1, "", str(e)


def lint(repo: Path) -> dict[str, Any]:
    code, stdout, stderr = _run(["ruff", "check", ".", "--statistics"], cwd=repo)
    lines = [ln for ln in (stdout + stderr).strip().splitlines() if ln.strip()]
    return {"ok": code == 0, "violations": len(lines) if code != 0 else 0, "details": lines[:10]}


def typecheck(repo: Path) -> dict[str, Any]:
    code, stdout, _stderr = _run(["pyright", "--outputjson"], cwd=repo)
    errors = 0
    if code != 0:
        try:
            data = json.loads(stdout)
            errors = data.get("summary", {}).get("errorCount", 0)
        except (json.JSONDecodeError, KeyError):
            errors = stdout.count("error:")
    return {"ok": code == 0, "errors": errors}


def tests(repo: Path) -> dict[str, Any]:
    code, stdout, _stderr = _run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--tb=no", "--no-header", "-n", "auto"],
        cwd=repo,
    )
    passed = 0
    failed = 0
    m_passed = _PYTEST_SUMMARY_RE.search(stdout)
    if m_passed:
        passed = int(m_passed.group(1))
    m_failed = _PYTEST_FAILED_RE.search(stdout)
    if m_failed:
        failed = int(m_failed.group(1))
    return {"ok": code == 0, "passed": passed, "failed": failed}


def stash_count(repo: Path) -> int:
    code, stdout, _ = _run(["git", "stash", "list"], cwd=repo)
    if code != 0:
        return 0
    return len([ln for ln in stdout.strip().splitlines() if ln.strip()])


def architecture(repo: Path) -> dict[str, Any]:
    code, stdout, _stderr = _run(
        [sys.executable, "-m", "pytest", "tests/unit/test_architecture.py", "-q", "--tb=short"],
        cwd=repo,
    )
    violations = [line.strip() for line in stdout.splitlines() if "FAILED" in line]
    return {"ok": code == 0, "violations": violations}


_PYRIGHT_SUMMARY_RE = re.compile(r"(\d+)\s+errors?,\s+(\d+)\s+warnings?,\s+(\d+)\s+informations?")
_PYTEST_SUMMARY_RE = re.compile(r"(\d+)\s+passed")
_PYTEST_FAILED_RE = re.compile(r"(\d+)\s+failed")
_RUFF_VIOLATION_RE = re.compile(r"Found\s+(\d+)\s+error")


def _calculate_score(
    lint_ok: bool,
    lint_violations: int,
    type_ok: bool,
    type_errors: int,
    test_ok: bool,
    test_failed: int,
    arch_violations: int = 0,
    stashes: int = 0,
) -> int:
    """Calculate health score from component results."""
    score = 100
    if not lint_ok:
        score -= min(20, lint_violations * 2)
    if not type_ok:
        score -= min(30, type_errors * 5)
    if not test_ok:
        score -= min(30, test_failed * 10)
    if arch_violations > 0:
        score -= min(10, arch_violations * 5)
    if stashes > 0:
        score -= min(10, stashes // 10)
    return max(0, score)


def _parse_ci_output(output: str) -> dict[str, Any]:
    lint_ok = "All checks passed" in output
    lint_violations = 0
    if not lint_ok:
        m = _RUFF_VIOLATION_RE.search(output)
        lint_violations = int(m.group(1)) if m else (1 if "ruff" in output.lower() else 0)

    type_errors = 0
    m = _PYRIGHT_SUMMARY_RE.search(output)
    type_ok = m is not None and int(m.group(1)) == 0
    if m:
        type_errors = int(m.group(1))
    elif "error" not in output.lower() or lint_ok:
        type_ok = True

    passed = 0
    failed = 0
    m = _PYTEST_SUMMARY_RE.search(output)
    if m:
        passed = int(m.group(1))
    m = _PYTEST_FAILED_RE.search(output)
    if m:
        failed = int(m.group(1))
    test_ok = failed == 0 and passed > 0

    return {
        "lint": {"ok": lint_ok, "violations": lint_violations, "details": []},
        "typecheck": {"ok": type_ok, "errors": type_errors},
        "tests": {"ok": test_ok, "passed": passed, "failed": failed},
    }


def _count_suppressions(repo: Path) -> int:
    """Count type-checking suppressions in the codebase."""
    try:
        pattern = r"# type: ignore|pyright: ignore"
        cmd = ["grep", "-rE", pattern, "space"]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo))
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        return len(lines)
    except Exception:
        return 0


def ci(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or Path.cwd()
    justfile = repo / "justfile"
    if not justfile.exists():
        return {"ok": True, "score": 100, "output": "no justfile", "ci": False}
    code, stdout, stderr = _run(["just", "ci"], cwd=repo)
    output = (stdout + stderr).strip()
    parsed = _parse_ci_output(output)
    ok = code == 0

    suppressions = _count_suppressions(repo)
    score = _calculate_score(
        parsed["lint"]["ok"],
        parsed["lint"]["violations"],
        parsed["typecheck"]["ok"],
        parsed["typecheck"]["errors"],
        parsed["tests"]["ok"],
        parsed["tests"]["failed"],
    )
    if suppressions > 0:
        score -= min(10, suppressions)
    score = max(0, score)

    return {
        "ok": ok,
        "score": score,
        "ci": True,
        "lint": parsed["lint"],
        "typecheck": parsed["typecheck"],
        "tests": parsed["tests"],
        "suppressions": suppressions,
        "architecture": {"ok": True, "violations": []},
        "stashes": 0,
    }


def health(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or Path.cwd()
    lint_result = lint(repo)
    type_result = typecheck(repo)
    test_result = tests(repo)
    arch_result = architecture(repo)
    stashes = stash_count(repo)

    ok = all([lint_result["ok"], type_result["ok"], test_result["ok"], arch_result["ok"]])

    score = _calculate_score(
        lint_result["ok"],
        lint_result["violations"],
        type_result["ok"],
        type_result["errors"],
        test_result["ok"],
        test_result["failed"],
        len(arch_result["violations"]),
        stashes,
    )

    return {
        "ok": ok,
        "score": score,
        "lint": lint_result,
        "typecheck": type_result,
        "tests": test_result,
        "architecture": arch_result,
        "stashes": stashes,
    }


def record(result: dict[str, Any], project_id: str | None = None) -> str:
    metric_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    with store.ensure() as conn:
        conn.execute(
            """INSERT INTO health_metrics
               (id, score, lint_violations, type_errors, test_passed, test_failed,
                arch_violations, suppressions, stashes, project_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                metric_id,
                result["score"],
                result.get("lint", {}).get("violations", 0),
                result.get("typecheck", {}).get("errors", 0),
                result.get("tests", {}).get("passed", 0),
                result.get("tests", {}).get("failed", 0),
                len(result.get("architecture", {}).get("violations", [])),
                result.get("suppressions", 0),
                result.get("stashes", 0),
                project_id,
                now,
            ),
        )
    return metric_id


def trend(limit: int = 10, project_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM health_metrics"
    params: list[Any] = []
    if project_id:
        query += " WHERE project_id = ?"
        params.append(project_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with store.ensure() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def degraded_dimensions(current: dict[str, Any], previous: dict[str, Any]) -> list[str]:
    degraded = []
    if current["lint"]["violations"] > previous.get("lint_violations", 0):
        degraded.append(
            f"lint: {current['lint']['violations']} violations (was {previous.get('lint_violations', 0)})"
        )
    if current["typecheck"]["errors"] > previous.get("type_errors", 0):
        degraded.append(
            f"types: {current['typecheck']['errors']} errors (was {previous.get('type_errors', 0)})"
        )
    if current["tests"]["failed"] > previous.get("test_failed", 0):
        degraded.append(
            f"tests: {current['tests']['failed']} failing (was {previous.get('test_failed', 0)})"
        )
    if current.get("suppressions", 0) > previous.get("suppressions", 0):
        degraded.append(
            f"types: {current['suppressions']} suppressions (was {previous.get('suppressions', 0)})"
        )
    prev_passed = previous.get("test_passed", 0)
    curr_passed = current["tests"]["passed"]
    if prev_passed > 0 and curr_passed == 0:
        degraded.append(f"tests: runner found 0 tests (was {prev_passed} passing)")
    if len(current["architecture"]["violations"]) > previous.get("arch_violations", 0):
        degraded.append(
            f"architecture: {len(current['architecture']['violations'])} violations (was {previous.get('arch_violations', 0)})"
        )
    return degraded
