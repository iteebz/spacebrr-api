import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from space.lib import store
from space.lib.commands import fail, space_cmd

console = Console()


IGNORE_PATTERNS = [
    ".git",
    ".claude",
    ".cogency",
    ".protoss",
    ".space",
    "dist",
    "build",
    ".astro",
    ".output",
    ".next",
    ".expo",
    ".nitro",
    "target",
    "venv",
    ".venv",
    ".pycache",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".hypothesis",
    "node_modules",
    ".pnpm_store",
    ".tanstack",
    ".turbo",
    ".DS_Store",
]


@space_cmd("tree")
def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        parser = argparse.ArgumentParser(description="Workspace topology.")
        parser.add_argument(
            "path", nargs="?", help="Directory to tree (default: workspace topology)"
        )
        parser.add_argument("-j", "--json", action="store_true", help="Output as JSON")
        parser.add_argument("-L", "--level", type=int, help="Max depth")
        parser.add_argument("-d", "--dirs-only", action="store_true", help="Directories only")

        if len(sys.argv) > 1 and sys.argv[1] == "tree":
            args = parser.parse_args(sys.argv[2:])
        else:
            args = parser.parse_args()

    if args.path:
        run_tree(Path(args.path), level=args.level, dirs_only=args.dirs_only)
    else:
        workspace = Path.home() / "space"
        data = build_topology(workspace)

        if args.json:
            console.print(json.dumps(data, indent=2))
        else:
            render_human(data)


def build_topology(workspace: Path) -> dict[str, Any]:
    workspace_repos = [
        get_repo_summary(item)
        for item in workspace.iterdir()
        if item.is_dir() and (item / ".git").exists() and item.name != "repos"
    ]

    external_repos = []
    repos_dir = workspace / "repos"
    if repos_dir.exists():
        external_repos.extend(
            get_repo_summary(item)
            for item in repos_dir.iterdir()
            if item.is_dir() and (item / ".git").exists()
        )

    return {
        "workspace": get_repo_info(workspace),
        "lattice": check_lattice_files(workspace),
        "repos": workspace_repos,
        "external": external_repos,
        "layers": analyze_spaceos(workspace / "space-os"),
        "spawns": count_spawns(),
    }


def get_repo_info(path: Path) -> dict[str, Any]:
    git_bin = shutil.which("git")
    if not git_bin:
        return {"path": str(path), "error": "git not found"}

    try:
        branch = subprocess.check_output(
            [git_bin, "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

        commit = subprocess.check_output(
            [git_bin, "-C", str(path), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

        total_commits = int(
            subprocess.check_output(
                [git_bin, "-C", str(path), "rev-list", "--count", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        )

        numstat = subprocess.check_output(
            [git_bin, "-C", str(path), "diff", "--numstat", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

        additions = 0
        deletions = 0
        if numstat:
            for line in numstat.split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0] != "-" and parts[1] != "-":
                    additions += int(parts[0])
                    deletions += int(parts[1])

        return {
            "path": str(path),
            "branch": branch,
            "commit": commit,
            "commits": total_commits,
            "additions": additions,
            "deletions": deletions,
        }
    except Exception:
        return {"path": str(path), "error": "not a git repo"}


def check_lattice_files(workspace: Path) -> list[dict[str, Any]]:
    lattice = [
        ("ARCH.md", "map"),
        ("SPACE.md", "compass"),
        ("CLAUDE.md", "constitution"),
    ]
    result: list[dict[str, Any]] = []
    for filename, role in lattice:
        path = workspace / filename
        entry: dict[str, Any] = {"file": filename, "role": role, "exists": path.exists()}
        if path.exists():
            entry["size"] = path.stat().st_size
        result.append(entry)
    return result


def get_repo_summary(path: Path) -> dict[str, Any]:
    info = get_repo_info(path)
    info["name"] = path.name
    info["summary"] = infer_summary(path)
    return info


def infer_summary(path: Path) -> str:
    name = path.name
    if name == "canon":
        count = len(list(path.glob("*.md")))
        return f"{count} invariants"
    if name == "blog":
        posts_dir = path / "posts"
        if posts_dir.exists():
            count = len(list(posts_dir.glob("*.md")))
            return f"{count} posts"
        return "blog"
    if name == "stream":
        count = len(list(path.glob("*.md")))
        return f"{count} entry" if count == 1 else f"{count} entries"
    if name == "space-os":
        return "codebase"
    return ""


def analyze_spaceos(spaceos: Path) -> dict[str, Any]:
    if not spaceos.exists():
        return {}

    space_dir = spaceos / "space"
    if not space_dir.exists():
        return {}

    layers = {}
    for layer in ["ledger", "agents", "stats", "lib", "ctx", "core", "cli"]:
        layer_path = space_dir / layer
        if not layer_path.exists():
            continue

        if layer == "ctx":
            identities_dir = layer_path / "identities"
            skills_dir = layer_path / "skills"
            identities = len(list(identities_dir.glob("*.md"))) if identities_dir.exists() else 0
            skills = len(list(skills_dir.glob("*.md"))) if skills_dir.exists() else 0
            layers[layer] = {
                "files": identities + skills,
                "summary": f"{identities} identities, {skills} skills",
            }
        else:
            modules = count_modules(layer_path)
            layers[layer] = {"modules": modules}
            if layer == "cli":
                layers[layer]["deprecated"] = True

    return layers


def count_modules(path: Path) -> int:
    if path.is_file() and path.suffix == ".py":
        return 1

    py_files = [f for f in path.rglob("*.py") if f.name != "__init__.py"]
    return len(py_files)


def infer_exports(path: Path) -> list[str]:
    init = path / "__init__.py"
    if not init.exists():
        return []

    try:
        content = init.read_text()
        exports = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("from .") and " import " in stripped:
                if " as " in stripped or "(" in stripped:
                    continue
                parts = stripped.split(" import ", 1)
                if len(parts) == 2:
                    imported = parts[1].split(",")[0].strip()
                    if imported:
                        exports.append(imported)
        return exports[:4]
    except Exception:
        return []


def count_spawns() -> dict[str, int]:
    try:
        with store.existing() as conn:
            active = conn.execute(
                "SELECT COUNT(*) FROM spawns WHERE status = 'running'"
            ).fetchone()[0]

            archived = conn.execute(
                "SELECT COUNT(*) FROM spawns WHERE status IN ('done', 'failed')"
            ).fetchone()[0]

        return {"active": int(active), "archived": int(archived)}
    except FileNotFoundError:
        return {"active": 0, "archived": 0}


def format_diff(additions: int, deletions: int) -> str:
    if additions == 0 and deletions == 0:
        return ""
    parts = []
    if additions > 0:
        parts.append(f"+{additions}")
    if deletions > 0:
        parts.append(f"-{deletions}")
    return "  " + "/".join(parts)


def render_human(data: dict[str, Any]) -> None:
    ws = data["workspace"]
    ws_label = "~/space/"

    total_repos = len(data["repos"]) + len(data.get("external", []))

    if "error" in ws:
        console.print(f"{ws_label:<32}  {ws['error']}")
    else:
        diff_str = format_diff(ws.get("additions", 0), ws.get("deletions", 0))
        console.print(f"{ws_label:<32}  {ws['branch']}  {total_repos} 🌳{diff_str}")

    for lattice_file in data["lattice"]:
        if lattice_file["exists"]:
            size_kb = lattice_file["size"] / 1024
            console.print(f"  {lattice_file['file']:<30}  {lattice_file['role']} ({size_kb:.1f}kb)")
        else:
            console.print(f"  {lattice_file['file']:<30}  {lattice_file['role']} (missing)")

    console.print()

    for repo in data["repos"]:
        diff_str = format_diff(repo.get("additions", 0), repo.get("deletions", 0))
        summary = f"  ({repo['summary']})" if repo["summary"] else ""
        repo_label = f"{repo['name']}/"
        console.print(
            f"  {repo_label:<30}  {repo['branch']}  {repo['commits']} commits{diff_str}{summary}"
        )

    if data["layers"]:
        console.print()
        console.print("    space/")
        for layer, info in data["layers"].items():
            layer_label = f"{layer}/"
            if layer == "ctx":
                console.print(
                    f"      {layer_label:<26}  {info['files']} files     {info['summary']}"
                )
            else:
                deprecated = " (deprecated)" if info.get("deprecated") else ""
                console.print(f"      {layer_label:<26}  {info['modules']} modules{deprecated}")

    if data["external"]:
        console.print()
        console.print("  repos/")
        for repo in data["external"]:
            diff_str = format_diff(repo.get("additions", 0), repo.get("deletions", 0))
            console.print(
                f"    {repo['name']:<28}  {repo['branch']}  {repo['commits']} commits{diff_str}"
            )

    spawns = data["spawns"]
    console.print()
    console.print(f"  {spawns['active']} active spawns, {spawns['archived']} archived")

    dirty_repos = sum(
        1
        for r in data["repos"] + data.get("external", [])
        if r.get("additions", 0) > 0 or r.get("deletions", 0) > 0
    )
    console.print(f"  {total_repos} trees tracked, {dirty_repos} dirty")


def run_tree(path: Path, level: int | None, dirs_only: bool) -> None:
    tree_bin = None
    for candidate in ["/opt/homebrew/bin/tree", "/usr/bin/tree", "/usr/local/bin/tree"]:
        if Path(candidate).exists():
            tree_bin = candidate
            break

    if not tree_bin:
        tree_bin = shutil.which("tree")
        if tree_bin and ".venv" in tree_bin:
            tree_bin = None

    if not tree_bin:
        fail("tree command not found (install via: brew install tree)")

    ignore = "|".join(IGNORE_PATTERNS)
    cmd = [tree_bin, "-a", "-C", "-I", ignore, "--dirsfirst"]

    if dirs_only:
        cmd.append("-d")
    if level is not None:
        cmd.extend(["-L", str(level)])

    cmd.append(str(path))

    subprocess.run(cmd)
