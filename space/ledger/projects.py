import json
import os
import sqlite3
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from space.core import ids
from space.core.errors import ConflictError, NotFoundError, ValidationError
from space.core.models import Project
from space.core.types import UNSET, ProjectId, Unset
from space.lib import paths, store
from space.lib.store.sqlite import placeholders

GLOBAL_PROJECT_ID = ProjectId("00000000-0000-0000-0000-000000000000")
GLOBAL_PROJECT_NAME = "_global"

_request_project_id: ContextVar[ProjectId | None] = ContextVar("request_project_id", default=None)


def set_request_scope(project_id: ProjectId | None) -> None:
    _request_project_id.set(project_id)


def get_request_scope() -> ProjectId | None:
    return _request_project_id.get()


def create(name: str, repo_path: str | None = None) -> Project:
    if not name:
        raise ValidationError("Project name is required")
    if " " in name:
        raise ValidationError("Project name cannot contain spaces")

    name = name.lower()
    resolved_repo = paths.resolve_cwd(repo_path) if repo_path else None
    project_id = ids.generate("projects")
    created_at = datetime.now(UTC).isoformat()

    with store.write() as conn:
        try:
            conn.execute(
                "INSERT INTO projects (id, name, type, repo_path, created_at) VALUES (?, ?, ?, ?, ?)",
                (project_id, name, "standard", resolved_repo, created_at),
            )
        except sqlite3.IntegrityError as e:
            err = str(e).lower()
            if "repo_path" in err:
                raise ConflictError(f"Repo path '{resolved_repo}' already registered") from e
            raise ConflictError(f"Project '{name}' already exists") from e

    return Project(
        id=ProjectId(project_id),
        name=name,
        repo_path=resolved_repo,
        created_at=created_at,
    )


def create_customer(
    name: str,
    repo_path: str,
    github_login: str,
    repo_url: str,
) -> Project:
    if not name or not github_login or not repo_url:
        raise ValidationError("name, github_login, and repo_url are required")
    if " " in name:
        raise ValidationError("Project name cannot contain spaces")

    name = name.lower()
    resolved_repo = paths.resolve_cwd(repo_path)
    project_id = ids.generate("projects")
    created_at = datetime.now(UTC).isoformat()

    with store.write() as conn:
        try:
            conn.execute(
                """INSERT INTO projects
                   (id, name, type, repo_path, github_login, repo_url, provisioned_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    name,
                    "customer",
                    resolved_repo,
                    github_login,
                    repo_url,
                    created_at,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as e:
            err = str(e).lower()
            if "repo_path" in err:
                raise ConflictError(f"Repo path '{resolved_repo}' already registered") from e
            raise ConflictError(f"Project '{name}' already exists") from e

    return Project(
        id=ProjectId(project_id),
        name=name,
        type="customer",
        repo_path=resolved_repo,
        github_login=github_login,
        repo_url=repo_url,
        provisioned_at=created_at,
        created_at=created_at,
    )


def fetch(include_archived: bool = False) -> list[Project]:
    where = "" if include_archived else "WHERE archived_at IS NULL"
    with store.ensure() as conn:
        rows = conn.execute(f"SELECT * FROM projects {where} ORDER BY name").fetchall()  # noqa: S608
    return [store.from_row(row, Project) for row in rows]


def batch_last_active(project_ids: list[ProjectId]) -> dict[ProjectId, str | None]:
    """Return latest activity timestamp per project based on primitives."""
    if not project_ids:
        return {}
    ph = ",".join("?" * len(project_ids))
    with store.ensure() as conn:
        rows = conn.execute(
            f"""
            SELECT project_id, MAX(created_at) AS ts FROM (
                SELECT project_id, created_at FROM insights WHERE project_id IN ({ph}) AND deleted_at IS NULL
                UNION ALL
                SELECT project_id, created_at FROM decisions WHERE project_id IN ({ph}) AND deleted_at IS NULL
                UNION ALL
                SELECT project_id, created_at FROM tasks WHERE project_id IN ({ph}) AND deleted_at IS NULL
            ) GROUP BY project_id
            """,  # noqa: S608
            project_ids * 3,
        ).fetchall()
    return {ProjectId(row[0]): row[1] for row in rows if row and row[0]}


def batch_artifact_counts(project_ids: list[ProjectId]) -> dict[ProjectId, int]:
    """Return total artifact count (insights + decisions + tasks) per project."""
    if not project_ids:
        return {}
    ph = ",".join("?" * len(project_ids))
    with store.ensure() as conn:
        rows = conn.execute(
            f"""
            SELECT project_id, COUNT(*) as cnt FROM (
                SELECT project_id FROM insights WHERE project_id IN ({ph}) AND deleted_at IS NULL
                UNION ALL
                SELECT project_id FROM decisions WHERE project_id IN ({ph}) AND deleted_at IS NULL
                UNION ALL
                SELECT project_id FROM tasks WHERE project_id IN ({ph}) AND deleted_at IS NULL
            ) GROUP BY project_id
            """,  # noqa: S608
            project_ids * 3,
        ).fetchall()
    return {ProjectId(row[0]): row[1] for row in rows if row and row[0]}


def last_active(project_id: ProjectId) -> str | None:
    res = batch_last_active([project_id])
    return res.get(project_id)


def get(project_id: ProjectId) -> Project:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise NotFoundError(project_id)
        return store.from_row(row, Project)


def try_get(project_id: ProjectId) -> Project | None:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return store.from_row(row, Project) if row else None


def batch_get(project_ids: list[ProjectId]) -> dict[ProjectId, Project]:
    if not project_ids:
        return {}
    ph = placeholders(project_ids)
    with store.ensure() as conn:
        rows = conn.execute(f"SELECT * FROM projects WHERE id IN ({ph})", project_ids).fetchall()  # noqa: S608
        return {ProjectId(row["id"]): store.from_row(row, Project) for row in rows}


def get_repo_path(project_id: str) -> Path | None:
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT repo_path FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return Path(row["repo_path"]) if row and row["repo_path"] else None


def update(
    project_id: ProjectId,
    name: str | None = None,
    repo_path: str | None | Unset = UNSET,
) -> Project:
    project = get(project_id)

    if name is not None and " " in name:
        raise ValidationError("Project name cannot contain spaces")
    if name is not None:
        name = name.lower()

    resolved_repo = paths.resolve_cwd(repo_path) if repo_path and repo_path is not UNSET else None
    if name is None and repo_path is UNSET:
        return project

    clear_repo_path = repo_path is None
    with store.write() as conn:
        try:
            conn.execute(
                """
                UPDATE projects
                SET name = COALESCE(?, name),
                    repo_path = CASE
                        WHEN ? THEN NULL
                        ELSE COALESCE(?, repo_path)
                    END
                WHERE id = ?
                """,
                (name, clear_repo_path, resolved_repo, project_id),
            )
        except sqlite3.IntegrityError as e:
            raise ConflictError(f"Project name '{name}' already exists") from e

        updated_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return store.from_row(updated_row, Project)


def set_type(project_id: ProjectId, type: str) -> Project:
    with store.write() as conn:
        conn.execute(
            "UPDATE projects SET type = ? WHERE id = ?",
            (type, project_id),
        )
    return get(project_id)


def archive(project_id: ProjectId, tags: list[str] | None = None) -> Project:
    with store.write() as conn:
        if tags:
            existing = get(project_id)
            merged = list(set((existing.tags or []) + tags))
            conn.execute(
                "UPDATE projects SET archived_at = CURRENT_TIMESTAMP, tags = ? WHERE id = ?",
                (json.dumps(merged), project_id),
            )
        else:
            conn.execute(
                "UPDATE projects SET archived_at = CURRENT_TIMESTAMP WHERE id = ?",
                (project_id,),
            )
    return get(project_id)


def restore(project_id: ProjectId) -> Project:
    with store.write() as conn:
        conn.execute(
            "UPDATE projects SET archived_at = NULL WHERE id = ?",
            (project_id,),
        )
    return get(project_id)


def add_tags(project_id: ProjectId, tags: list[str]) -> Project:
    if not tags:
        return get(project_id)
    project = get(project_id)
    existing = project.tags or []
    merged = list(set(existing + tags))
    with store.write() as conn:
        conn.execute(
            "UPDATE projects SET tags = ? WHERE id = ?",
            (json.dumps(merged), project_id),
        )
    return get(project_id)


def remove_tags(project_id: ProjectId, tags: list[str]) -> Project:
    if not tags:
        return get(project_id)
    project = get(project_id)
    existing = project.tags or []
    remaining = [t for t in existing if t not in tags]
    with store.write() as conn:
        conn.execute(
            "UPDATE projects SET tags = ? WHERE id = ?",
            (json.dumps(remaining) if remaining else None, project_id),
        )
    return get(project_id)


def set_tags(project_id: ProjectId, tags: list[str] | None) -> Project:
    with store.write() as conn:
        conn.execute(
            "UPDATE projects SET tags = ? WHERE id = ?",
            (json.dumps(tags) if tags else None, project_id),
        )
    return get(project_id)


def fetch_by_tag(tag: str, include_archived: bool = True) -> list[Project]:
    all_projects = fetch(include_archived=include_archived)
    return [p for p in all_projects if p.tags and tag in p.tags]


def find_git_root(start: Path | None = None) -> Path | None:
    """Walk up from start looking for .git (file or directory). Stops at $HOME."""
    cwd = (start or Path.cwd()).resolve()
    home = Path.home().resolve()

    for parent in [cwd, *cwd.parents]:
        if parent == home.parent:
            break
        if (parent / ".git").exists():
            return parent
    return None


def find_by_path(git_root: Path) -> Project | None:
    """Match git root against known project repo_paths."""
    resolved = git_root.resolve()
    for project in fetch():
        if project.repo_path and Path(project.repo_path).resolve() == resolved:
            return project
    return None


def infer_from_cwd() -> Project | None:
    """Infer project from CWD by finding git root and matching to known"""
    start_path = (
        Path(os.environ["SPACE_INVOCATION_DIR"]) if "SPACE_INVOCATION_DIR" in os.environ else None
    )
    if git_root := find_git_root(start_path):
        return find_by_path(git_root)
    return None


def ensure_global() -> Project:
    """Get or create the _global project for cross-project work."""
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ? LIMIT 1",
            (GLOBAL_PROJECT_ID,),
        ).fetchone()
        if row:
            return store.from_row(row, Project)

    created_at = datetime.now(UTC).isoformat()
    with store.write() as conn:
        try:
            conn.execute(
                "INSERT INTO projects (id, name, type, repo_path, created_at) VALUES (?, ?, ?, ?, ?)",
                (GLOBAL_PROJECT_ID, GLOBAL_PROJECT_NAME, "standard", None, created_at),
            )
        except sqlite3.IntegrityError:
            with store.ensure() as conn2:
                row = conn2.execute(
                    "SELECT * FROM projects WHERE id = ? LIMIT 1",
                    (GLOBAL_PROJECT_ID,),
                ).fetchone()
                if not row:
                    raise
                return store.from_row(row, Project)

    return Project(
        id=GLOBAL_PROJECT_ID,
        name=GLOBAL_PROJECT_NAME,
        repo_path=None,
        created_at=created_at,
    )


def get_scope(project_ref: str | None = None) -> ProjectId:
    """Get project scope from: explicit ref -> request -> CWD -> _global."""
    if project_ref:
        project = store.resolve(project_ref, "projects", Project)
        return project.id

    if request_scope := get_request_scope():
        return request_scope

    if project := infer_from_cwd():
        return project.id

    return ensure_global().id


def require_scope() -> ProjectId:
    """Get project scope (always succeeds - defaults to _global)."""
    return get_scope()


def last_touched_at(project_id: ProjectId) -> str | None:
    """Get most recent activity timestamp from human agents for a project.

    Checks insights, decisions, tasks, and replies created by humans.
    Returns ISO timestamp or None if no human activity exists.
    """
    with store.ensure() as conn:
        row = conn.execute(
            """
            SELECT MAX(ts) as last_touched FROM (
                SELECT i.created_at as ts
                FROM insights i
                JOIN agents a ON a.id = i.agent_id
                WHERE i.project_id = ? AND a.type = 'human' AND i.deleted_at IS NULL
                UNION ALL
                SELECT d.created_at as ts
                FROM decisions d
                JOIN agents a ON a.id = d.agent_id
                WHERE d.project_id = ? AND a.type = 'human' AND d.deleted_at IS NULL
                UNION ALL
                SELECT t.created_at as ts
                FROM tasks t
                JOIN agents a ON a.id = t.creator_id
                WHERE t.project_id = ? AND a.type = 'human' AND t.deleted_at IS NULL
                UNION ALL
                SELECT r.created_at as ts
                FROM replies r
                JOIN agents a ON a.id = r.author_id
                WHERE r.project_id = ? AND a.type = 'human' AND r.deleted_at IS NULL
            )
            """,
            (project_id, project_id, project_id, project_id),
        ).fetchone()
        return row["last_touched"] if row else None
