import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from space.lib import paths

Author = tuple[str, str]  # (name, email)


@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    commit: str
    is_detached: bool


@dataclass
class DiffStat:
    files_changed: int
    insertions: int
    deletions: int
    raw: str


@dataclass
class MergeCheck:
    can_merge: bool
    conflicts: list[str]
    base_branch: str


class GitError(Exception):
    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


def _run(
    args: list[str],
    cwd: Path | None = None,
    author: Author | None = None,
) -> subprocess.CompletedProcess[str]:
    env = None
    if author:
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = author[0]
        env["GIT_AUTHOR_EMAIL"] = author[1]
        env["GIT_COMMITTER_NAME"] = author[0]
        env["GIT_COMMITTER_EMAIL"] = author[1]
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "no error output"
        raise GitError(f"git command failed: {' '.join(args)}\nError: {stderr}", stderr)
    return result


def _run_silent(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def clone_bare(url: str, target_path: Path) -> Path:
    if target_path.exists():
        return target_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--bare", url, str(target_path)])
    return target_path


def init_bare(target_path: Path) -> Path:
    if target_path.exists():
        return target_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "--bare", str(target_path)])
    return target_path


def ensure_branch(repo: Path, branch: str) -> bool:
    if branch_exists(repo, branch):
        return False
    default = get_default_branch(repo)
    _run(["git", "-C", str(repo), "branch", branch, default])
    return True


def get_default_branch(repo: Path) -> str:
    for branch in ["main", "master"]:
        check = _run_silent(["git", "-C", str(repo), "rev-parse", "--verify", branch])
        if check.returncode == 0:
            return branch

    result = _run_silent(["git", "-C", str(repo), "symbolic-ref", "HEAD"])
    if result.returncode == 0:
        return result.stdout.strip().replace("refs/heads/", "")

    return "main"


def create_worktree(
    repo: Path,
    branch: str,
    base_branch: str | None = None,
) -> Path:
    paths.ensure_dirs()
    repo_name = repo.stem.replace(".git", "")
    worktree_path = paths.trees_dir() / f"{repo_name}--{branch}"

    if worktree_path.exists():
        raise GitError(f"Worktree already exists: {worktree_path}")

    _fetch_if_remote(repo)

    if base_branch is None:
        base_branch = get_default_branch(repo)

    _run(
        [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            base_branch,
        ]
    )
    return worktree_path


def remove_worktree(repo: Path, worktree_path: Path, force: bool = False):
    if not worktree_path.exists():
        return
    args = ["git", "-C", str(repo), "worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree_path))
    _run_silent(args)


def delete_branch(bare_repo: Path, branch: str, force: bool = False):
    flag = "-D" if force else "-d"
    _run(["git", "-C", str(bare_repo), "branch", flag, branch])


def _parse_worktree(data: dict[str, str]) -> WorktreeInfo:
    return WorktreeInfo(
        path=Path(data["worktree"]),
        branch=data.get("branch", "").replace("refs/heads/", ""),
        commit=data.get("HEAD", ""),
        is_detached="detached" in data,
    )


def list_worktrees(bare_repo: Path) -> list[WorktreeInfo]:
    result = _run(["git", "-C", str(bare_repo), "worktree", "list", "--porcelain"])

    worktrees: list[WorktreeInfo] = []
    current: dict[str, str] = {}

    for line in result.stdout.strip().split("\n"):
        if not line:
            if current and "worktree" in current:
                worktrees.append(_parse_worktree(current))
            current = {}
        elif line.startswith("worktree "):
            current["worktree"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "):
            current["HEAD"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]
        elif line == "detached":
            current["detached"] = "true"

    if current and "worktree" in current:
        worktrees.append(_parse_worktree(current))

    return worktrees


def get_diff_stat(worktree_path: Path, base: str | None = None) -> DiffStat:
    if base is None:
        base = get_default_branch(worktree_path)

    result = _run_silent(["git", "-C", str(worktree_path), "diff", "--stat", base])

    files_changed = 0
    insertions = 0
    deletions = 0
    raw = result.stdout.strip()

    if raw:
        lines = raw.split("\n")
        if lines:
            summary = lines[-1]
            parts = summary.split(", ")
            for part in parts:
                if "file" in part:
                    files_changed = int(part.split()[0])
                elif "insertion" in part:
                    insertions = int(part.split()[0])
                elif "deletion" in part:
                    deletions = int(part.split()[0])

    return DiffStat(
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
        raw=raw,
    )


def commit_count(worktree_path: Path, base: str | None = None) -> int:
    ahead, _ = diverged(worktree_path, base)
    return ahead


def diverged(worktree_path: Path, base: str | None = None, fetch: bool = False) -> tuple[int, int]:
    if base is None:
        base = get_default_branch(worktree_path)

    if fetch:
        _run_silent(["git", "-C", str(worktree_path), "fetch", "origin", base])

    result = _run_silent(
        ["git", "-C", str(worktree_path), "rev-list", "--left-right", "--count", f"{base}...HEAD"]
    )
    if result.returncode != 0:
        return 0, 0

    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0

    behind, ahead = int(parts[0]), int(parts[1])
    return ahead, behind


def dirty(worktree_path: Path) -> bool:
    result = _run_silent(["git", "-C", str(worktree_path), "status", "--porcelain"])
    return bool(result.stdout.strip())


def _build_commit_message(message: str, trailers: dict[str, str] | None) -> str:
    if not trailers:
        return message
    trailer_lines = "\n".join(f"{k}: {v}" for k, v in trailers.items())
    return f"{message}\n\n{trailer_lines}"


def merge(
    repo: Path,
    branch: str,
    target_branch: str | None = None,
    message: str | None = None,
    author: Author | None = None,
    trailers: dict[str, str] | None = None,
) -> str:
    if not _validate_branch(branch):
        raise GitError(f"Invalid branch name: {branch}")
    if target_branch is None:
        target_branch = get_default_branch(repo)
    elif not _validate_branch(target_branch):
        raise GitError(f"Invalid target branch name: {target_branch}")

    _run(["git", "-C", str(repo), "checkout", target_branch])
    _run(["git", "-C", str(repo), "merge", "--squash", branch])
    commit_msg = _build_commit_message(message or f"Merge {branch}", trailers)
    _run(["git", "-C", str(repo), "commit", "-m", commit_msg], author=author)

    result = _run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    return result.stdout.strip()


def push_branch(bare_repo: Path, branch: str, remote: str = "origin"):
    _run(["git", "-C", str(bare_repo), "push", remote, branch])


def sync(bare_repo: Path, remote: str = "origin"):
    _run(["git", "-C", str(bare_repo), "fetch", remote])


def _fetch_if_remote(bare_repo: Path):
    result = _run_silent(["git", "-C", str(bare_repo), "remote"])
    remotes = result.stdout.strip().split("\n") if result.stdout.strip() else []
    if "origin" in remotes:
        _run_silent(["git", "-C", str(bare_repo), "fetch", "origin"])


def worktree_exists(bare_repo: Path, branch: str) -> bool:
    worktrees = list_worktrees(bare_repo)
    return any(wt.branch == branch for wt in worktrees)


def branch_exists(bare_repo: Path, branch: str) -> bool:
    result = _run_silent(["git", "-C", str(bare_repo), "rev-parse", "--verify", branch])
    return result.returncode == 0


def current_branch(repo: Path) -> str | None:
    result = _run_silent(["git", "-C", str(repo), "symbolic-ref", "--short", "HEAD"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def sanitize_branch(name: str) -> str:
    safe = name.lower()
    safe = safe.replace(" ", "-")
    safe = "".join(c for c in safe if c.isalnum() or c in "-_")
    safe = safe.strip("-_")
    return safe or "branch"


def validate_branch(name: str) -> bool:
    return _validate_branch(name)


def _validate_branch(name: str) -> bool:
    if not name or ".." in name or name.startswith("-"):
        return False
    return all(c.isalnum() or c in "-_/." for c in name)


def get_commit_timestamp(commit: str, repo: Path | None = None) -> str | None:
    cwd = repo or Path.cwd()
    result = _run_silent(["git", "-C", str(cwd), "show", "-s", "--format=%cI", commit])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def get_commits(worktree_path: Path, base: str | None = None) -> list[dict[str, str]]:
    if base is None:
        base = get_default_branch(worktree_path)

    result = _run_silent(
        ["git", "-C", str(worktree_path), "log", f"{base}..HEAD", "--format=%H|%s"]
    )
    if result.returncode != 0:
        return []

    commits: list[dict[str, str]] = []
    for line in result.stdout.strip().split("\n"):
        if line and "|" in line:
            hash_part, msg = line.split("|", 1)
            commits.append({"hash": hash_part, "message": msg})
    return commits


def compute_worktree_path(repo: Path, branch: str) -> Path:
    repo_name = repo.stem.replace(".git", "")
    return paths.trees_dir() / f"{repo_name}--{branch}"


def rename_branch(bare_repo: Path, old_branch: str, new_branch: str):
    _run(["git", "-C", str(bare_repo), "branch", "-m", old_branch, new_branch])


def restore_worktree(repo: Path, branch: str) -> Path:
    if not branch_exists(repo, branch):
        raise GitError(f"Branch does not exist: {branch}")

    paths.ensure_dirs()
    worktree_path = compute_worktree_path(repo, branch)

    if worktree_path.exists():
        raise GitError(f"Worktree already exists: {worktree_path}")

    _run(["git", "-C", str(repo), "worktree", "add", str(worktree_path), branch])
    return worktree_path


def ensure_worktree(repo: Path, branch: str) -> Path:
    worktree_path = compute_worktree_path(repo, branch)

    if worktree_path.exists():
        return worktree_path

    return restore_worktree(repo, branch)


def check_merge(
    repo: Path,
    branch: str,
    target_branch: str | None = None,
) -> MergeCheck:
    if target_branch is None:
        target_branch = get_default_branch(repo)

    result = _run_silent(
        ["git", "-C", str(repo), "merge-tree", "--write-tree", target_branch, branch]
    )

    if result.returncode == 0:
        return MergeCheck(can_merge=True, conflicts=[], base_branch=target_branch)

    conflicts = [line for line in result.stdout.split("\n") if line.startswith("CONFLICT")]
    return MergeCheck(can_merge=False, conflicts=conflicts, base_branch=target_branch)


def clean_worktree(
    bare_repo: Path,
    worktree_path: Path,
    branch: str,
    do_merge: bool = False,
    commit_message: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"merged": False, "commit": None}

    if do_merge:
        try:
            commit_hash = merge(
                bare_repo,
                branch,
                message=commit_message or f"Merge {branch}",
            )
            result["merged"] = True
            result["commit"] = commit_hash
        except GitError:
            raise

    if worktree_path.exists():
        remove_worktree(bare_repo, worktree_path, force=True)
    delete_branch(bare_repo, branch, force=True)

    return result
