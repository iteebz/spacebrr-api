from dataclasses import dataclass
from datetime import UTC, datetime

from space.core.models import Decision, Insight, Reply, Task
from space.core.types import AgentId, ArtifactType, ProjectId, SpawnId
from space.lib import store


@dataclass
class InboxItem:
    type: str
    id: str
    content: str
    author_id: str
    created_at: str
    parent_id: str | None = None
    parent_type: str | None = None
    reason: str = "mention"


def fetch(agent_handle: str, project_id: ProjectId | None = None) -> list[InboxItem]:
    """Unified inbox: all artifacts requiring agent attention."""
    with store.ensure() as conn:
        agent_row = conn.execute(
            "SELECT id FROM agents WHERE handle = ? AND deleted_at IS NULL",
            (agent_handle,),
        ).fetchone()
        if not agent_row:
            return []
        agent_id = agent_row["id"]

        project_filter = "AND r.project_id = ?" if project_id else ""
        project_filter_i = "AND i.project_id = ?" if project_id else ""
        project_filter_d = "AND d.project_id = ?" if project_id else ""
        project_filter_t = "AND t.project_id = ?" if project_id else ""
        project_param = (project_id,) if project_id else ()

        rows = conn.execute(
            f"""
            WITH latest_mentions AS (
              SELECT r.id, r.parent_type, r.parent_id,
                     ROW_NUMBER() OVER (PARTITION BY r.parent_type, r.parent_id ORDER BY r.created_at DESC) as rn
              FROM replies r
              JOIN agents a ON r.author_id = a.id
              WHERE r.mentions LIKE ?
                AND r.deleted_at IS NULL
                AND a.handle != ?
                {project_filter}
            )
            SELECT
              'reply' as type,
              r.id,
              r.content,
              r.author_id,
              r.created_at,
              r.parent_id,
              r.parent_type,
              'mention' as reason
            FROM replies r
            JOIN latest_mentions lm ON r.id = lm.id
            WHERE lm.rn = 1
              {project_filter}
              AND NOT EXISTS (
                SELECT 1 FROM replies r2
                JOIN agents a2 ON r2.author_id = a2.id
                WHERE r2.parent_type = r.parent_type
                  AND r2.parent_id = r.parent_id
                  AND a2.handle = ?
                  AND r2.created_at > r.created_at
                  AND r2.deleted_at IS NULL
              )
              AND NOT EXISTS (
                SELECT 1 FROM human_resolutions hr
                WHERE hr.artifact_type = r.parent_type
                  AND hr.artifact_id = r.parent_id
                  AND hr.resolved_at > r.created_at
              )
              AND NOT EXISTS (
                SELECT 1 FROM artifact_reads ar
                WHERE ar.artifact_type = r.parent_type
                  AND ar.artifact_id = r.parent_id
                  AND ar.agent_id = ?
                  AND ar.read_at > r.created_at
              )
              AND (
                (r.parent_type = 'insight' AND NOT EXISTS (
                  SELECT 1 FROM insights i WHERE i.id = r.parent_id AND (i.archived_at IS NOT NULL OR i.deleted_at IS NOT NULL)
                ))
                OR (r.parent_type = 'decision' AND NOT EXISTS (
                  SELECT 1 FROM decisions d WHERE d.id = r.parent_id AND d.deleted_at IS NOT NULL
                ))
                OR (r.parent_type = 'task' AND NOT EXISTS (
                  SELECT 1 FROM tasks t WHERE t.id = r.parent_id AND (t.status IN ('done', 'cancelled') OR t.deleted_at IS NOT NULL)
                ))
              )

            UNION ALL

            SELECT
              'insight' as type,
              i.id,
              i.content,
              i.agent_id,
              i.created_at,
              NULL as parent_id,
              NULL as parent_type,
              'mention' as reason
            FROM insights i
            WHERE i.mentions LIKE ?
              AND i.deleted_at IS NULL
              AND i.archived_at IS NULL
              AND i.agent_id != ?
              {project_filter_i}
              AND NOT EXISTS (
                SELECT 1 FROM replies r
                JOIN agents a ON r.author_id = a.id
                WHERE r.parent_type = 'insight'
                  AND r.parent_id = i.id
                  AND a.handle = ?
                  AND r.deleted_at IS NULL
              )
              AND NOT EXISTS (
                SELECT 1 FROM human_resolutions hr
                WHERE hr.artifact_type = 'insight'
                  AND hr.artifact_id = i.id
                  AND hr.resolved_at > i.created_at
              )
              AND NOT EXISTS (
                SELECT 1 FROM artifact_reads ar
                WHERE ar.artifact_type = 'insight'
                  AND ar.artifact_id = i.id
                  AND ar.agent_id = ?
                  AND ar.read_at > i.created_at
              )

            UNION ALL

            SELECT
              'insight' as type,
              i.id,
              i.content,
              i.agent_id,
              i.created_at,
              NULL as parent_id,
              NULL as parent_type,
              'question_reply' as reason
            FROM insights i
            WHERE i.open = 1
              AND i.agent_id = ?
              AND i.deleted_at IS NULL
              AND i.archived_at IS NULL
              {project_filter_i}
              AND EXISTS (
                SELECT 1 FROM replies r
                WHERE r.parent_type = 'insight'
                  AND r.parent_id = i.id
                  AND r.deleted_at IS NULL
                  AND r.created_at > COALESCE(
                    (SELECT MAX(r2.created_at) FROM replies r2
                     WHERE r2.parent_type = 'insight'
                       AND r2.parent_id = i.id
                       AND r2.author_id = ?
                       AND r2.deleted_at IS NULL),
                    i.created_at
                  )
              )
              AND NOT EXISTS (
                SELECT 1 FROM human_resolutions hr
                WHERE hr.artifact_type = 'insight'
                  AND hr.artifact_id = i.id
                  AND hr.resolved_at > i.created_at
              )
              AND NOT EXISTS (
                SELECT 1 FROM artifact_reads ar
                WHERE ar.artifact_type = 'insight'
                  AND ar.artifact_id = i.id
                  AND ar.agent_id = ?
                  AND ar.read_at > i.created_at
              )

            UNION ALL

            SELECT
              'insight' as type,
              i.id,
              i.content,
              i.agent_id,
              i.created_at,
              NULL as parent_id,
              NULL as parent_type,
              'open_question' as reason
            FROM insights i
            WHERE i.open = 1
              AND i.mentions LIKE ?
              AND i.deleted_at IS NULL
              AND i.archived_at IS NULL
              AND i.agent_id != ?
              {project_filter_i}
              AND NOT EXISTS (
                SELECT 1 FROM replies r
                JOIN agents a ON r.author_id = a.id
                WHERE r.parent_type = 'insight'
                  AND r.parent_id = i.id
                  AND a.handle = ?
                  AND r.deleted_at IS NULL
              )
              AND NOT EXISTS (
                SELECT 1 FROM human_resolutions hr
                WHERE hr.artifact_type = 'insight'
                  AND hr.artifact_id = i.id
                  AND hr.resolved_at > i.created_at
              )
              AND NOT EXISTS (
                SELECT 1 FROM artifact_reads ar
                WHERE ar.artifact_type = 'insight'
                  AND ar.artifact_id = i.id
                  AND ar.agent_id = ?
                  AND ar.read_at > i.created_at
              )

            UNION ALL

            SELECT
              'decision' as type,
              d.id,
              d.content,
              d.agent_id,
              d.created_at,
              NULL as parent_id,
              NULL as parent_type,
              'open_discussion' as reason
            FROM decisions d
            WHERE d.committed_at IS NOT NULL
              AND d.actioned_at IS NULL
              AND d.rejected_at IS NULL
              AND d.deleted_at IS NULL
              AND d.agent_id != ?
              {project_filter_d}
              AND EXISTS (
                SELECT 1 FROM replies r
                WHERE r.parent_type = 'decision'
                  AND r.parent_id = d.id
                  AND r.deleted_at IS NULL
              )
              AND NOT EXISTS (
                SELECT 1 FROM replies r
                JOIN agents a ON r.author_id = a.id
                WHERE r.parent_type = 'decision'
                  AND r.parent_id = d.id
                  AND a.handle = ?
                  AND r.deleted_at IS NULL
              )
              AND NOT EXISTS (
                SELECT 1 FROM artifact_reads ar
                WHERE ar.artifact_type = 'decision'
                  AND ar.artifact_id = d.id
                  AND ar.agent_id = ?
                  AND ar.read_at > d.created_at
              )

            UNION ALL

            SELECT
              'task' as type,
              t.id,
              t.content,
              t.assignee_id,
              t.created_at,
              NULL as parent_id,
              NULL as parent_type,
              'assigned' as reason
            FROM tasks t
            WHERE t.assignee_id = ?
              AND t.status IN ('pending', 'active')
              AND t.deleted_at IS NULL
              {project_filter_t}

            ORDER BY created_at DESC
            """,  # noqa: S608
            (
                # CTE: latest_mentions
                f'%"{agent_handle}"%',
                agent_handle,
                *project_param,
                # Reply select
                agent_handle,
                agent_id,
                *project_param,
                # Insight mention
                f'%"{agent_handle}"%',
                agent_id,
                *project_param,
                agent_handle,
                agent_id,
                # Insight question_reply
                agent_id,
                *project_param,
                agent_id,
                agent_id,
                # Insight open_question
                f'%"{agent_handle}"%',
                agent_id,
                *project_param,
                agent_handle,
                agent_id,
                # Decision open_discussion
                agent_id,
                *project_param,
                agent_handle,
                agent_id,
                # Task assigned
                agent_id,
                *project_param,
            ),
        ).fetchall()

    return [store.from_row(row, InboxItem) for row in rows]


def fetch_replies(agent_handle: str) -> list[Reply]:
    """Legacy: reply mentions only."""
    items = fetch(agent_handle)
    reply_ids = [item.id for item in items if item.type == "reply"]
    if not reply_ids:
        return []
    with store.ensure() as conn:
        placeholders = ",".join("?" * len(reply_ids))
        rows = conn.execute(
            f"SELECT * FROM replies WHERE id IN ({placeholders})",  # noqa: S608
            reply_ids,
        ).fetchall()
    return [store.from_row(row, Reply) for row in rows]


def fetch_insights(agent_handle: str) -> list[Insight]:
    """Legacy: insight mentions and open questions."""
    items = fetch(agent_handle)
    insight_ids = [item.id for item in items if item.type == "insight"]
    if not insight_ids:
        return []
    with store.ensure() as conn:
        placeholders = ",".join("?" * len(insight_ids))
        rows = conn.execute(
            f"SELECT * FROM insights WHERE id IN ({placeholders})",  # noqa: S608
            insight_ids,
        ).fetchall()
    return [store.from_row(row, Insight) for row in rows]


def fetch_decisions(agent_handle: str) -> list[Decision]:
    """Open decisions with discussion agent hasn't joined."""
    items = fetch(agent_handle)
    decision_ids = [item.id for item in items if item.type == "decision"]
    if not decision_ids:
        return []
    with store.ensure() as conn:
        placeholders = ",".join("?" * len(decision_ids))
        rows = conn.execute(
            f"SELECT * FROM decisions WHERE id IN ({placeholders})",  # noqa: S608
            decision_ids,
        ).fetchall()
    return [store.from_row(row, Decision) for row in rows]


def fetch_tasks(agent_handle: str) -> list[Task]:
    """Tasks assigned to agent."""
    items = fetch(agent_handle)
    task_ids = [item.id for item in items if item.type == "task"]
    if not task_ids:
        return []
    with store.ensure() as conn:
        placeholders = ",".join("?" * len(task_ids))
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE id IN ({placeholders})",  # noqa: S608
            task_ids,
        ).fetchall()
    return [store.from_row(row, Task) for row in rows]


def agents_with_inbox() -> set[str]:
    """Agent handles with non-empty inboxes."""
    with store.ensure() as conn:
        rows = conn.execute("SELECT handle FROM agents WHERE deleted_at IS NULL").fetchall()
    handles = {row["handle"] for row in rows}
    return {handle for handle in handles if fetch(handle)}


def mark_read(
    artifact_type: ArtifactType,
    artifact_id: str,
    agent_id: AgentId,
    spawn_id: SpawnId | None = None,
) -> None:
    """Record artifact read. Clears from inbox without creating reply artifact."""
    now = datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            """
            INSERT INTO artifact_reads (artifact_type, artifact_id, agent_id, spawn_id, read_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(artifact_type, artifact_id, agent_id)
            DO UPDATE SET read_at = excluded.read_at, spawn_id = excluded.spawn_id
            """,
            (artifact_type, artifact_id, agent_id, spawn_id, now),
        )


def mark_resolved(artifact_type: ArtifactType, artifact_id: str, agent_id: AgentId) -> None:
    """Mark artifact as resolved by human."""
    now = datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            """
            INSERT INTO human_resolutions (artifact_type, artifact_id, resolved_by, resolved_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(artifact_type, artifact_id)
            DO UPDATE SET resolved_by = excluded.resolved_by, resolved_at = excluded.resolved_at
            """,
            (artifact_type, artifact_id, agent_id, now),
        )


def is_resolved(artifact_type: ArtifactType, artifact_id: str) -> bool:
    """Check if artifact has been resolved by human."""
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT 1 FROM human_resolutions WHERE artifact_type = ? AND artifact_id = ?",
            (artifact_type, artifact_id),
        ).fetchone()
    return row is not None


def get_resolved_at(artifact_type: ArtifactType, artifact_id: str) -> str | None:
    """Get timestamp when artifact was resolved, or None if not resolved."""
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT resolved_at FROM human_resolutions WHERE artifact_type = ? AND artifact_id = ?",
            (artifact_type, artifact_id),
        ).fetchone()
    return row["resolved_at"] if row else None


def unresolve(artifact_type: ArtifactType, artifact_id: str) -> None:
    """Remove resolution marker (undo)."""
    with store.write() as conn:
        conn.execute(
            "DELETE FROM human_resolutions WHERE artifact_type = ? AND artifact_id = ?",
            (artifact_type, artifact_id),
        )
