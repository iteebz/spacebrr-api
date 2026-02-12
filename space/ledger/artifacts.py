from datetime import UTC, datetime

from space.core.errors import NotFoundError
from space.core.types import ArtifactType, ProjectId
from space.lib import store


def resolve(parent_id: str) -> tuple[ArtifactType, str]:
    """Resolve an artifact by full id or prefix.

    Returns (artifact_type, full_id). Only resolves non-deleted artifacts.
    """
    with store.ensure() as conn:
        for table, ptype in (("insights", "insight"), ("decisions", "decision"), ("tasks", "task")):
            row = conn.execute(
                f"SELECT id FROM {table} WHERE id LIKE ? AND deleted_at IS NULL",  # noqa: S608
                (f"{parent_id}%",),
            ).fetchone()
            if row:
                return ptype, row["id"]  # type: ignore[return-value]
    raise NotFoundError(f"No artifact found matching '{parent_id}'")


def get_project_id(parent_type: ArtifactType, parent_id: str) -> ProjectId | None:
    """Return project_id for given artifact."""
    table = f"{parent_type}s"
    with store.ensure() as conn:
        row = conn.execute(
            f"SELECT project_id FROM {table} WHERE id = ?",  # noqa: S608
            (parent_id,),
        ).fetchone()
    return ProjectId(row["project_id"]) if row and row["project_id"] else None


def is_closed(parent_type: ArtifactType, parent_id: str) -> bool:
    """Return True if an artifact should be treated as closed for inbox/triage views."""
    with store.ensure() as conn:
        if parent_type == "task":
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (parent_id,)).fetchone()
            return row is not None and row["status"] in ("done", "cancelled")

        table = f"{parent_type}s"
        row = conn.execute(
            f"SELECT archived_at, deleted_at FROM {table} WHERE id = ?",  # noqa: S608
            (parent_id,),
        ).fetchone()
        if not row:
            return True
        return row["archived_at"] is not None or row["deleted_at"] is not None


def soft_delete(table: str, id: str, typename: str) -> None:
    """Soft delete a ledger primitive by setting deleted_at timestamp."""
    now = datetime.now(UTC).isoformat()
    with store.write() as conn:
        cursor = conn.execute(
            f"UPDATE {table} SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",  # noqa: S608
            (now, id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"{typename} '{id}' not found or already deleted")


def archive(table: str, id: str, typename: str) -> None:
    """Archive a ledger primitive by setting archived_at timestamp."""
    now = datetime.now(UTC).isoformat()
    with store.write() as conn:
        cursor = conn.execute(
            f"UPDATE {table} SET archived_at = ? WHERE id = ? AND archived_at IS NULL",  # noqa: S608
            (now, id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"{typename} '{id}' not found or already archived")
