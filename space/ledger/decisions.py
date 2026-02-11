import json
from datetime import UTC, datetime

from space import agents
from space.core import ids
from space.core.errors import NotFoundError, ValidationError
from space.core.models import Decision, DecisionStatus, Insight
from space.core.types import AgentId, DecisionId, ProjectId, SpawnId
from space.ledger import artifacts
from space.lib import citations, store


def _check_duplicate(content: str, project_id: ProjectId) -> DecisionId | None:
    """Return existing decision ID if exact duplicate exists, else None."""
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT id FROM decisions WHERE content = ? AND project_id = ? AND deleted_at IS NULL",
            (content, project_id),
        ).fetchone()
        return DecisionId(row["id"]) if row else None


def create(
    project_id: ProjectId,
    agent_id: AgentId,
    content: str,
    rationale: str,
    spawn_id: SpawnId | None = None,
    images: list[str] | None = None,
    expected_outcome: str | None = None,
    refs: str | None = None,
    reversible: bool | None = None,
) -> Decision:
    if not rationale or not rationale.strip():
        raise ValidationError("rationale is required")

    existing = _check_duplicate(content, project_id)
    if existing:
        raise ValidationError(f"Duplicate decision exists: {existing}")

    decision_id = DecisionId(ids.generate("decisions"))
    now = datetime.now(UTC).isoformat()

    with store.write() as conn:
        store.unarchive("agents", agent_id, conn)
        conn.execute(
            "INSERT INTO decisions (id, project_id, agent_id, spawn_id, content, rationale, images, expected_outcome, refs, reversible, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision_id,
                project_id,
                agent_id,
                spawn_id,
                content,
                rationale,
                json.dumps(images) if images else None,
                expected_outcome,
                refs,
                1 if reversible is True else (0 if reversible is False else None),
                now,
            ),
        )
        citation_text = f"{content} {rationale}"
        if refs:
            citation_text = f"{citation_text} {refs}"
        citations.store(conn, "decision", decision_id, citation_text)
    return get(decision_id)


def get(decision_id: DecisionId) -> Decision:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        if not row:
            raise NotFoundError(decision_id)
        return store.from_row(row, Decision)


def fetch(
    agent_id: AgentId | None = None,
    spawn_id: SpawnId | None = None,
    limit: int | None = None,
    project_id: ProjectId | None = None,
) -> list[Decision]:
    with store.ensure() as conn:
        return (
            store.q("decisions")
            .active()
            .where_if("project_id = ?", project_id)
            .where_if("agent_id = ?", agent_id)
            .where_if("spawn_id = ?", spawn_id)
            .order("created_at DESC")
            .limit(limit)
            .fetch(conn, Decision)
        )


def delete(decision_id: DecisionId) -> None:
    """Soft delete. No hard deletes on decisions - provenance is sacred."""
    artifacts.soft_delete("decisions", decision_id, "Decision")


def reassign(decision_id: DecisionId, project_id: ProjectId) -> Decision:
    with store.write() as conn:
        cursor = conn.execute(
            "UPDATE decisions SET project_id = ? WHERE id = ? AND deleted_at IS NULL",
            (project_id, decision_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Decision '{decision_id}' not found")
    return get(decision_id)


def archive(decision_id: DecisionId) -> Decision:
    """Archive a decision. Removes from active view but preserves history."""
    artifacts.archive("decisions", decision_id, "Decision")
    return get(decision_id)


def action(
    decision_id: DecisionId,
    at: str | None = None,
    outcome: str | None = None,
) -> Decision:
    """Mark decision as actioned (reality contact). One-shot, immutable."""
    decision = get(decision_id)
    if decision.actioned_at:
        raise ValidationError(
            f"Decision '{decision_id}' already actioned at {decision.actioned_at}"
        )
    if decision.rejected_at:
        raise ValidationError(f"Decision '{decision_id}' already rejected - cannot action")
    if not decision.committed_at:
        raise ValidationError(f"Decision '{decision_id}' not yet committed - cannot action")

    now = at or datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            "UPDATE decisions SET actioned_at = ?, outcome = ? WHERE id = ?",
            (now, outcome, decision_id),
        )
    return get(decision_id)


def fetch_by_status(
    status: DecisionStatus | str,
    project_id: ProjectId | None = None,
    limit: int | None = None,
) -> list[Decision]:
    """Fetch decisions by derived status: proposed, committed, actioned, learned, rejected.

    Status is derived from timestamps + linked insights:
    - proposed: not committed
    - committed: committed but not actioned
    - actioned: actioned with no insights created after actioned_at
    - learned: actioned with at least one insight created after actioned_at
    - rejected: rejected_at is set
    """
    if not isinstance(status, DecisionStatus):
        try:
            status = DecisionStatus(status)
        except ValueError as e:
            raise ValidationError(f"Unknown status: {status}") from e

    conditions = ["d.deleted_at IS NULL", "d.archived_at IS NULL"]
    params: list[str | int] = []

    if project_id:
        conditions.append("d.project_id = ?")
        params.append(project_id)

    if status == DecisionStatus.REJECTED:
        conditions.append("d.rejected_at IS NOT NULL")
    else:
        conditions.append("d.rejected_at IS NULL")

    if status == DecisionStatus.PROPOSED:
        conditions.append("d.committed_at IS NULL")
    elif status == DecisionStatus.COMMITTED:
        conditions.append("d.committed_at IS NOT NULL")
        conditions.append("d.actioned_at IS NULL")
    elif status == DecisionStatus.ACTIONED:
        conditions.append("d.committed_at IS NOT NULL")
        conditions.append("d.actioned_at IS NOT NULL")
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM insights i WHERE i.decision_id = d.id "
            "AND i.deleted_at IS NULL AND i.created_at > d.actioned_at)"
        )
    elif status == DecisionStatus.LEARNED:
        conditions.append("d.committed_at IS NOT NULL")
        conditions.append("d.actioned_at IS NOT NULL")
        conditions.append(
            "EXISTS (SELECT 1 FROM insights i WHERE i.decision_id = d.id "
            "AND i.deleted_at IS NULL AND i.created_at > d.actioned_at)"
        )

    where = " AND ".join(conditions)
    sql = f"SELECT d.* FROM decisions d WHERE {where} ORDER BY d.created_at DESC"  # noqa: S608

    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    with store.ensure() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [store.from_row(row, Decision) for row in rows]


def get_status(decision: Decision, linked_insights: list[Insight]) -> DecisionStatus:
    """Derive status from timestamps and linked insights.

    Caller must provide linked_insights — no hidden I/O.
    """
    if decision.rejected_at:
        return DecisionStatus.REJECTED

    if not decision.committed_at:
        return DecisionStatus.PROPOSED

    if not decision.actioned_at:
        return DecisionStatus.COMMITTED

    qualifying = [i for i in linked_insights if i.created_at > decision.actioned_at]
    return DecisionStatus.LEARNED if qualifying else DecisionStatus.ACTIONED


def is_human_blocked(decision: Decision) -> bool:
    """Check if decision requires @human action (committed but content mentions @human)."""
    if not decision.committed_at or decision.actioned_at or decision.rejected_at:
        return False
    return agents.at_human(decision.content)


def set_reversible(decision_id: DecisionId, reversible: bool) -> Decision:
    """Mark whether a decision is reversible. Affects delegation threshold."""
    decision = get(decision_id)
    if decision.actioned_at:
        raise ValidationError(
            f"Decision '{decision_id}' already actioned - cannot change reversibility"
        )
    if decision.rejected_at:
        raise ValidationError(
            f"Decision '{decision_id}' already rejected - cannot change reversibility"
        )
    with store.write() as conn:
        conn.execute(
            "UPDATE decisions SET reversible = ? WHERE id = ?",
            (1 if reversible else 0, decision_id),
        )
    return get(decision_id)


def commit(decision_id: DecisionId, at: str | None = None) -> Decision:
    """Commit a proposed decision. Makes it binding. One-shot, immutable."""
    decision = get(decision_id)
    if decision.committed_at:
        raise ValidationError(
            f"Decision '{decision_id}' already committed at {decision.committed_at}"
        )
    if decision.rejected_at:
        raise ValidationError(f"Decision '{decision_id}' already rejected - cannot commit")

    now = at or datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            "UPDATE decisions SET committed_at = ? WHERE id = ?",
            (now, decision_id),
        )
    return get(decision_id)


def reject(decision_id: DecisionId, at: str | None = None) -> Decision:
    """Reject decision (explicitly not pursuing). One-shot, immutable."""
    decision = get(decision_id)
    if decision.rejected_at:
        raise ValidationError(
            f"Decision '{decision_id}' already rejected at {decision.rejected_at}"
        )
    if decision.actioned_at:
        raise ValidationError(f"Decision '{decision_id}' already actioned - cannot reject")

    now = at or datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            "UPDATE decisions SET rejected_at = ? WHERE id = ?",
            (now, decision_id),
        )
    return get(decision_id)


def uncommit(decision_id: DecisionId) -> Decision:
    """Revert COMMITTED decision to PROPOSED. Used for decay mechanisms."""
    decision = get(decision_id)
    if not decision.committed_at:
        raise ValidationError(f"Decision '{decision_id}' not committed")
    if decision.actioned_at:
        raise ValidationError(f"Decision '{decision_id}' already actioned - cannot uncommit")
    if decision.rejected_at:
        raise ValidationError(f"Decision '{decision_id}' already rejected - cannot uncommit")

    with store.write() as conn:
        conn.execute(
            "UPDATE decisions SET committed_at = NULL WHERE id = ?",
            (decision_id,),
        )
    return get(decision_id)


def decay_human_blocked(hours: int = 48) -> list[DecisionId]:
    """Decay COMMITTED decisions with @human blockers older than hours to PROPOSED.

    Returns list of decision IDs that were decayed.
    """
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT id FROM decisions
            WHERE committed_at IS NOT NULL
              AND actioned_at IS NULL
              AND rejected_at IS NULL
              AND deleted_at IS NULL
              AND archived_at IS NULL
              AND (julianday('now') - julianday(committed_at)) * 24 >= ?
            """,
            (hours,),
        ).fetchall()

    decayed = []
    for row in rows:
        decision_id = DecisionId(row["id"])
        decision = get(decision_id)
        if is_human_blocked(decision):
            uncommit(decision_id)
            decayed.append(decision_id)

    return decayed


def count(project_id: ProjectId | None = None) -> int:
    with store.ensure() as conn:
        return store.q("decisions").active().where_if("project_id = ?", project_id).count(conn)


def fetch_stale(
    project_id: ProjectId | None = None,
    max_refs: int = 2,
    min_age_hours: int = 24,
    limit: int = 10,
) -> list[tuple[Decision, int]]:
    """Fetch committed decisions with low reference counts (staleness candidates).

    Returns list of (decision, ref_count) ordered by ref_count ascending.
    A decision is stale if it's committed, has few references, and is old enough.
    """
    with store.ensure() as conn:
        params: list[str | int] = [min_age_hours, max_refs]

        base_query = """
            SELECT d.*,
                (
                    SELECT COUNT(*) FROM citations c
                    WHERE c.target_type = 'decision' AND c.target_short_id = substr(d.id, 1, 8)
                ) + (
                    SELECT COUNT(*) FROM replies r
                    WHERE r.parent_id = d.id AND r.deleted_at IS NULL
                ) + (
                    SELECT COUNT(*) FROM insights i2
                    WHERE i2.decision_id = d.id AND i2.deleted_at IS NULL
                ) as total_refs
            FROM decisions d
            WHERE d.committed_at IS NOT NULL
              AND d.actioned_at IS NULL
              AND d.rejected_at IS NULL
              AND d.deleted_at IS NULL
              AND d.archived_at IS NULL
              AND (julianday('now') - julianday(d.committed_at)) * 24 >= ?
        """

        if project_id:
            base_query += " AND d.project_id = ?"
            params.insert(1, project_id)

        query = f"""
            SELECT * FROM ({base_query}) sub
            WHERE total_refs <= ?
            ORDER BY total_refs ASC, committed_at ASC LIMIT {limit}
        """  # noqa: S608
        rows = conn.execute(query, params).fetchall()

    return [(store.from_row(row, Decision), row["total_refs"]) for row in rows]


def fetch_rejected_with_reasons(
    project_id: ProjectId | None = None, limit: int = 5, max_age_days: int = 30
) -> list[tuple[Decision, str | None]]:
    """Fetch recently rejected decisions with their rejection reasons.

    Returns list of (decision, reason) tuples. Reason extracted from reply.
    """
    with store.ensure() as conn:
        params: list[str | int] = [max_age_days]
        query = """
            SELECT d.*, r.content as reason
            FROM decisions d
            LEFT JOIN replies r ON r.parent_id = d.id
                AND r.content LIKE 'Rejected:%'
                AND r.deleted_at IS NULL
            WHERE d.rejected_at IS NOT NULL
                AND d.deleted_at IS NULL
                AND d.archived_at IS NULL
                AND julianday('now') - julianday(d.rejected_at) <= ?
        """
        if project_id:
            query += " AND d.project_id = ?"
            params.append(project_id)

        query += " ORDER BY d.rejected_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(query, params).fetchall()

    results: list[tuple[Decision, str | None]] = []
    for row in rows:
        decision = store.from_row(dict(row), Decision)
        reason = row["reason"]
        if reason and reason.startswith("Rejected: "):
            reason = reason[10:]
        results.append((decision, reason))
    return results


def fetch_calibration(project_id: ProjectId | None = None, limit: int = 50) -> list[Decision]:
    """Fetch decisions with both reversibility judgment and outcome recorded."""
    with store.ensure() as conn:
        params: list[str | int] = []
        query = """
            SELECT * FROM decisions
            WHERE reversible IS NOT NULL
              AND outcome IS NOT NULL
              AND deleted_at IS NULL
              AND archived_at IS NULL
        """
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)

        query += " ORDER BY actioned_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(query, params).fetchall()
    return [store.from_row(row, Decision) for row in rows]
