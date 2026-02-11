import os
from pathlib import Path


def _env_override(env_var: str) -> Path | None:
    if value := os.environ.get(env_var):
        return Path(value)
    return None


def spawn_id() -> str | None:
    return os.environ.get("SPACE_SPAWN_ID")


def space_root() -> Path:
    return _env_override("SPACE_ROOT") or Path.home() / "space"


def repos_dir() -> Path:
    return _env_override("SPACE_REPOS_DIR") or space_root() / "repos"


def trees_dir() -> Path:
    if override := _env_override("SPACE_TREES_DIR"):
        return override
    return repos_dir() / "trees"


def dot_space() -> Path:
    return _env_override("SPACE_DOT_SPACE") or Path.home() / ".space"


def backups_dir() -> Path:
    return _env_override("SPACE_BACKUPS_DIR") or Path.home() / ".space_backups"


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def identity_dir(identity: str) -> Path:
    return dot_space() / "agents" / identity


def avatar_path(identity: str) -> Path | None:
    base = dot_space() / "images" / "avatars"
    if not base.exists():
        return None
    matches = list(base.glob(f"{identity}.*"))
    return max(matches, key=lambda p: p.stat().st_mtime) if matches else None


def resolve_cwd(path: str) -> str:
    if not path:
        return path
    if path.startswith(("/", "~")):
        return str(Path(path).expanduser().resolve())

    head, _, tail = path.partition("/")
    if head == "repos":
        return str((repos_dir() / tail).resolve()) if tail else str(repos_dir().resolve())
    if head == "trees":
        return str((trees_dir() / tail).resolve()) if tail else str(trees_dir().resolve())

    return str((space_root() / path).resolve())


def ensure_dirs() -> None:
    for d in [
        dot_space(),
        dot_space() / "spawns",
        dot_space() / "sessions",
        dot_space() / "images" / "avatars",
        dot_space() / "images" / "uploads",
        repos_dir(),
        trees_dir(),
    ]:
        d.mkdir(parents=True, exist_ok=True)
