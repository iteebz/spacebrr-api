import subprocess
from collections import defaultdict
from datetime import datetime
from typing import Any

from space import agents


def _extract_domain(msg: str) -> str | None:
    if "(" in msg and ")" in msg:
        return msg[msg.index("(") + 1 : msg.index(")")]
    return None


def code_extension() -> dict[str, Any]:
    ai_agents = {a.handle for a in agents.fetch(type="ai")}

    def get_file_authors(filepath: str, n_commits: int = 100) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "log", f"-{n_commits}", "--format=%an", "--", filepath],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip().split("\n")
        except subprocess.CalledProcessError:
            return []

    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    files = [
        f for f in result.stdout.strip().split("\n") if f.endswith((".py", ".ts", ".tsx", ".md"))
    ]

    extensions: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for filepath in files:
        authors = get_file_authors(filepath)
        if len(authors) < 2:
            continue

        seen: set[str] = set()
        for i, author in enumerate(authors):
            if author not in ai_agents or author in seen:
                continue
            for prior in authors[i + 1 :]:
                if prior in ai_agents and prior != author and prior not in seen:
                    extensions[author][prior] += 1
            seen.add(author)

    totals = {ext: sum(priors.values()) for ext, priors in extensions.items()}
    total_extensions = sum(totals.values())

    return {
        "by_agent": {
            ext: {"total": totals[ext], "extends": dict(priors)}
            for ext, priors in extensions.items()
        },
        "total": total_extensions,
    }


def cross_agent_corrections(days: int = 7) -> dict[str, Any]:
    ai_agents = {a.handle for a in agents.fetch(type="ai")}

    try:
        result = subprocess.run(
            ["git", "log", f"--since={days} days ago", "--format=%H|%an|%s"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return {"error": "git log failed", "corrections": 0, "total_fixes": 0, "rate": 0}

    lines = [line for line in result.stdout.strip().split("\n") if line]
    if not lines:
        return {"days": days, "corrections": 0, "total_fixes": 0, "rate": 0, "pairs": []}

    commits = []
    for line in lines:
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        commit_hash, author, msg = parts
        commits.append(
            {"hash": commit_hash, "author": author, "msg": msg, "domain": _extract_domain(msg)}
        )

    corrections: dict[tuple[str, str], int] = defaultdict(int)
    total_fixes = 0

    for i, commit in enumerate(commits):
        author = commit["author"]
        msg = commit["msg"]

        if not msg.lower().startswith("fix") or author not in ai_agents:
            continue

        total_fixes += 1
        domain = commit["domain"]

        for j in range(i + 1, min(i + 50, len(commits))):
            prev = commits[j]
            if prev["author"] == author or prev["author"] not in ai_agents:
                continue
            if prev["msg"].lower().startswith("fix"):
                continue
            if domain and prev["domain"] == domain:
                corrections[(author, prev["author"])] += 1
                break

    pairs = [
        {"fixer": k[0], "broke": k[1], "count": v}
        for k, v in sorted(corrections.items(), key=lambda x: -x[1])
    ]
    total_corrections = sum(corrections.values())
    rate = round(total_corrections / total_fixes * 100, 1) if total_fixes else 0

    return {
        "days": days,
        "corrections": total_corrections,
        "total_fixes": total_fixes,
        "rate": rate,
        "pairs": pairs,
    }


def agent_commit_stats(days: int = 7) -> dict[str, Any]:
    ai_agents = {a.handle for a in agents.fetch(type="ai")}

    try:
        result = subprocess.run(
            ["git", "log", f"--since={days} days ago", "--format=%H|%an|%ai", "--numstat"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return {"error": "git log failed", "by_agent": [], "days": days}

    lines = result.stdout.strip().split("\n")
    if not lines:
        return {"days": days, "by_agent": [], "total": {"commits": 0, "added": 0, "removed": 0}}

    by_agent: dict[str, dict[str, int]] = defaultdict(
        lambda: {"commits": 0, "added": 0, "removed": 0}
    )

    current_author = None
    for line in lines:
        if "|" in line:
            parts = line.split("|")
            if len(parts) >= 2:
                current_author = parts[1]
                if current_author in ai_agents:
                    by_agent[current_author]["commits"] += 1
        elif current_author and current_author in ai_agents and "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 2:
                try:
                    added = int(parts[0]) if parts[0] != "-" else 0
                    removed = int(parts[1]) if parts[1] != "-" else 0
                    by_agent[current_author]["added"] += added
                    by_agent[current_author]["removed"] += removed
                except ValueError:
                    pass

    results = []
    for agent, counts in sorted(by_agent.items(), key=lambda x: -x[1]["commits"]):
        net = counts["added"] - counts["removed"]
        results.append(
            {
                "agent": agent,
                "commits": counts["commits"],
                "added": counts["added"],
                "removed": counts["removed"],
                "net": net,
            }
        )

    total_commits = sum(r["commits"] for r in results)
    total_added = sum(r["added"] for r in results)
    total_removed = sum(r["removed"] for r in results)

    return {
        "days": days,
        "by_agent": results,
        "total": {"commits": total_commits, "added": total_added, "removed": total_removed},
    }


def commit_stability(days: int = 7) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", "log", f"--since={days} days ago", "--format=%H|%an|%s|%ai"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return {"error": "git log failed", "by_agent": [], "overall": {}}

    lines = [line for line in result.stdout.strip().split("\n") if line]
    if not lines:
        return {"days": days, "by_agent": [], "overall": {"total": 0, "fixes": 0, "fix_rate": 0}}

    commits = []
    for line in lines:
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        commit_hash, author, msg, timestamp = parts
        try:
            clean = timestamp.replace(" +", "+").replace(" -", "-")
            if "+" in clean:
                dt = datetime.fromisoformat(clean.split("+")[0].replace(" ", "T"))
            else:
                dt = datetime.fromisoformat(clean.replace(" ", "T"))
        except ValueError:
            dt = None
        commits.append(
            {
                "hash": commit_hash,
                "author": author,
                "msg": msg,
                "dt": dt,
                "domain": _extract_domain(msg),
            }
        )

    by_agent: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "self_fixes": 0, "other_fixes": 0}
    )

    for i, commit in enumerate(commits):
        author = commit["author"]
        msg = commit["msg"]
        by_agent[author]["total"] += 1

        if msg.lower().startswith("fix"):
            domain = commit["domain"]
            is_refinement = False
            for j in range(i + 1, min(i + 20, len(commits))):
                prev = commits[j]
                if prev["author"] != author:
                    continue
                if prev["msg"].lower().startswith("fix"):
                    continue
                within_6h = (
                    commit["dt"]
                    and prev["dt"]
                    and (commit["dt"] - prev["dt"]).total_seconds() < 21600
                )
                same_domain = domain and prev["domain"] == domain
                if within_6h and same_domain:
                    is_refinement = True
                    break

            if is_refinement:
                by_agent[author]["self_fixes"] += 1
            else:
                by_agent[author]["other_fixes"] += 1

    results = []
    for agent, counts in sorted(by_agent.items(), key=lambda x: -x[1]["total"]):
        fix_rate = round(counts["other_fixes"] / counts["total"] * 100, 1) if counts["total"] else 0
        results.append(
            {
                "agent": agent,
                "total": counts["total"],
                "self_fixes": counts["self_fixes"],
                "other_fixes": counts["other_fixes"],
                "fix_rate": fix_rate,
            }
        )

    total = sum(r["total"] for r in results)
    other_fixes = sum(r["other_fixes"] for r in results)
    overall_rate = round(other_fixes / total * 100, 1) if total else 0

    return {
        "days": days,
        "by_agent": results,
        "overall": {"total": total, "other_fixes": other_fixes, "fix_rate": overall_rate},
    }
