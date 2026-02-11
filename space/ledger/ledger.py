"""Ledger: unified timeline of primitives."""

import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from space.core.types import AgentId, DecisionId, InsightId, ProjectId, TaskId
from space.lib import store
from space.lib.store.resolve import by_prefix

LedgerItemType = Literal["insight", "decision", "task", "reply"]


@dataclass
class LedgerItem:
    type: LedgerItemType
    id: str
    content: str
    agent_id: AgentId
    handle: str
    created_at: str
    rationale: str | None = None
    status: str | None = None
    decision_id: DecisionId | None = None
    decision_content: str | None = None
    reply_count: int = 0


def _item_from_row(row: dict[str, Any]) -> LedgerItem:
    return LedgerItem(
        type=row["type"],
        id=row["id"],
        content=row["content"],
        rationale=row.get("rationale"),
        status=row.get("status"),
        agent_id=row["agent_id"],
        handle=row["handle"],
        created_at=row["created_at"],
        decision_id=row.get("decision_id"),
        decision_content=row.get("decision_content"),
        reply_count=row.get("reply_count", 0),
    )


def _fetch_replies(conn: sqlite3.Connection, parent_type: str, parent_id: str) -> list[LedgerItem]:
    rows = conn.execute(
        """
        SELECT 'reply' as type, r.id, r.content, NULL as rationale, NULL as status,
               r.author_id as agent_id, a.handle, r.created_at
        FROM replies r
        JOIN agents a ON r.author_id = a.id
        WHERE r.parent_type = ? AND r.parent_id = ? AND r.deleted_at IS NULL
        ORDER BY r.created_at ASC
        """,
        (parent_type, parent_id),
    ).fetchall()
    return [_item_from_row(dict(row)) for row in rows]


def fetch(limit: int = 50, project_id: ProjectId | None = None) -> list[LedgerItem]:
    """Fetch recent primitives as a unified ledger."""
    project_filter = "AND i.project_id = ?" if project_id else ""
    task_project_filter = "AND t.project_id = ?" if project_id else ""
    decision_project_filter = "AND d.project_id = ?" if project_id else ""

    query = f"""
        SELECT * FROM (
            SELECT 'insight' as type, i.id, i.content, NULL as rationale, NULL as status,
                   i.agent_id, a.handle, i.created_at, i.decision_id, d.content as decision_content,
                   (SELECT COUNT(*) FROM replies r WHERE r.parent_type = 'insight' AND r.parent_id = i.id AND r.deleted_at IS NULL) as reply_count
            FROM insights i
            JOIN agents a ON i.agent_id = a.id
            LEFT JOIN decisions d ON i.decision_id = d.id
            WHERE i.deleted_at IS NULL {project_filter}
            UNION ALL
            SELECT 'decision', d.id, d.content, d.rationale, NULL,
                   d.agent_id, a.handle, d.created_at, NULL, NULL,
                   (SELECT COUNT(*) FROM replies r WHERE r.parent_type = 'decision' AND r.parent_id = d.id AND r.deleted_at IS NULL)
            FROM decisions d JOIN agents a ON d.agent_id = a.id WHERE d.deleted_at IS NULL {decision_project_filter}
            UNION ALL
            SELECT 'task', t.id, t.content, NULL, t.status,
                   t.creator_id, a.handle, t.created_at, t.decision_id, d.content,
                   0
            FROM tasks t
            JOIN agents a ON t.creator_id = a.id
            LEFT JOIN decisions d ON t.decision_id = d.id
            WHERE 1=1 {task_project_filter}
        )
        ORDER BY created_at DESC
        LIMIT ?
    """  # noqa: S608

    params: list[str | int] = []
    if project_id:
        params.extend([project_id, project_id, project_id])
    params.append(limit)

    with store.ensure() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_item_from_row(dict(row)) for row in rows]


def thread(item_type: str, item_id: str) -> tuple[LedgerItem | None, list[LedgerItem]]:
    """Fetch an artifact and all items linked to it. Accepts full UUID or 8+ char prefix."""
    if item_type == "decision":
        full_id = by_prefix(item_id, "decisions", "id", DecisionId)
        if not full_id:
            return None, []
        return _decision_thread(full_id)
    if item_type == "insight":
        full_id = by_prefix(item_id, "insights", "id", InsightId)
        if not full_id:
            return None, []
        return _insight_thread(full_id)
    if item_type == "task":
        full_id = by_prefix(item_id, "tasks", "id", TaskId)
        if not full_id:
            return None, []
        return _task_thread(full_id)
    return None, []


def _decision_thread(decision_id: DecisionId) -> tuple[LedgerItem | None, list[LedgerItem]]:
    with store.ensure() as conn:
        dec_row = conn.execute(
            """
            SELECT 'decision' as type, d.id, d.content, d.rationale, NULL as status,
                   d.agent_id, a.handle, d.created_at, NULL as decision_id, NULL as decision_content
            FROM decisions d
            JOIN agents a ON d.agent_id = a.id
            WHERE d.id = ? AND d.deleted_at IS NULL
            """,
            (decision_id,),
        ).fetchone()

        if not dec_row:
            return None, []

        linked = conn.execute(
            """
            SELECT * FROM (
                SELECT 'insight' as type, i.id, i.content, NULL as rationale, NULL as status,
                       i.agent_id, a.handle, i.created_at
                FROM insights i
                JOIN agents a ON i.agent_id = a.id
                WHERE i.decision_id = ? AND i.deleted_at IS NULL
                UNION ALL
                SELECT 'task', t.id, t.content, NULL, t.status,
                       t.creator_id, a.handle, t.created_at
                FROM tasks t
                JOIN agents a ON t.creator_id = a.id
                WHERE t.decision_id = ?
                UNION ALL
                SELECT 'reply', r.id, r.content, NULL, NULL,
                       r.author_id, a.handle, r.created_at
                FROM replies r
                JOIN agents a ON r.author_id = a.id
                WHERE r.parent_type = 'decision' AND r.parent_id = ?
                    AND r.deleted_at IS NULL
            )
            ORDER BY created_at ASC
            """,
            (decision_id, decision_id, decision_id),
        ).fetchall()

    return _item_from_row(dict(dec_row)), [_item_from_row(dict(row)) for row in linked]


def _insight_thread(insight_id: InsightId) -> tuple[LedgerItem | None, list[LedgerItem]]:
    with store.ensure() as conn:
        ins_row = conn.execute(
            """
            SELECT 'insight' as type, i.id, i.content, NULL as rationale, NULL as status,
                   i.agent_id, a.handle, i.created_at, i.decision_id, d.content as decision_content
            FROM insights i
            JOIN agents a ON i.agent_id = a.id
            LEFT JOIN decisions d ON i.decision_id = d.id
            WHERE i.id = ? AND i.deleted_at IS NULL
            """,
            (insight_id,),
        ).fetchone()

        if not ins_row:
            return None, []

        replies = _fetch_replies(conn, "insight", insight_id)

    return _item_from_row(dict(ins_row)), replies


def _task_thread(task_id: TaskId) -> tuple[LedgerItem | None, list[LedgerItem]]:
    with store.ensure() as conn:
        task_row = conn.execute(
            """
            SELECT 'task' as type, t.id, t.content, NULL as rationale, t.status,
                   t.creator_id as agent_id, a.handle, t.created_at, t.decision_id,
                   d.content as decision_content
            FROM tasks t
            JOIN agents a ON t.creator_id = a.id
            LEFT JOIN decisions d ON t.decision_id = d.id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()

        if not task_row:
            return None, []

        replies = _fetch_replies(conn, "task", task_id)

    return _item_from_row(dict(task_row)), replies
