import json
import logging
from datetime import UTC, datetime, timedelta

from space.core import ids
from space.core.errors import NotFoundError, ValidationError
from space.core.models import Insight
from space.core.types import AgentId, DecisionId, InsightId, ProjectId, SpawnId
from space.ledger import artifacts, replies
from space.lib import citations, nlp, store

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 280


def _compute_provenance(content: str, author_id: AgentId) -> str:
    """Compute insight provenance based on cross-agent citations."""
    cited = citations.extract(content)
    if not cited:
        return "solo"

    with store.ensure() as conn:
        cross_agent_count = 0
        for target_type, short_id in cited:
            table = "insights" if target_type == "insight" else "decisions"
            row = conn.execute(
                f"SELECT agent_id FROM {table} WHERE id LIKE ? AND deleted_at IS NULL",  # noqa: S608
                (f"{short_id}%",),
            ).fetchone()
            if row and row["agent_id"] != author_id:
                cross_agent_count += 1

    if cross_agent_count >= 2:
        return "synthesis"
    if cross_agent_count == 1:
        return "collaborative"
    return "solo"


def validate_domain(domain: str) -> str:
    return domain


def _check_duplicate(content: str, project_id: ProjectId) -> InsightId | None:
    """Return existing insight ID if exact duplicate exists, else None."""
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT id FROM insights WHERE content = ? AND project_id = ? AND deleted_at IS NULL",
            (content, project_id),
        ).fetchone()
        return InsightId(row["id"]) if row else None


def create(
    project_id: ProjectId,
    agent_id: AgentId,
    content: str,
    domain: str,
    spawn_id: SpawnId | None = None,
    decision_id: DecisionId | None = None,
    images: list[str] | None = None,
    open: bool = False,
) -> Insight:
    domain = validate_domain(domain)

    existing = _check_duplicate(content, project_id)
    if existing:
        raise ValidationError(f"Duplicate insight exists: {existing}")

    if len(content) > MAX_CONTENT_LENGTH:
        raise ValidationError(
            f"Insight content exceeds {MAX_CONTENT_LENGTH} characters ({len(content)}). "
            "Insights must be atomic - compress or log a decision with rationale instead."
        )

    if decision_id:
        with store.ensure() as conn:
            row = conn.execute(
                "SELECT id FROM decisions WHERE id = ? AND deleted_at IS NULL",
                (decision_id,),
            ).fetchone()
            if not row:
                raise ValidationError(
                    f"Decision '{decision_id}' not found — cannot link insight to nonexistent decision"
                )

    insight_id = InsightId(ids.generate("insights"))
    now = datetime.now(UTC).isoformat()
    mentions = replies.parse_mentions(content)
    provenance = _compute_provenance(content, agent_id)

    with store.write() as conn:
        store.unarchive("agents", agent_id, conn)
        if decision_id:
            store.unarchive("decisions", decision_id, conn)
        conn.execute(
            "INSERT INTO insights (id, project_id, agent_id, spawn_id, decision_id, domain, content, images, open, mentions, created_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                insight_id,
                project_id,
                agent_id,
                spawn_id,
                decision_id,
                domain,
                content,
                json.dumps(images) if images else None,
                1 if open else 0,
                json.dumps(mentions) if mentions else None,
                now,
                provenance,
            ),
        )
        citations.store(conn, "insight", insight_id, content)
    return get(insight_id)


def get(insight_id: InsightId) -> Insight:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM insights WHERE id = ?", (insight_id,)).fetchone()
        if not row:
            raise NotFoundError(insight_id)
        return store.from_row(row, Insight)


def domains() -> list[str]:
    with store.ensure() as conn:
        rows = conn.execute(
            "SELECT DISTINCT domain FROM insights WHERE deleted_at IS NULL ORDER BY domain"
        ).fetchall()
        return [row["domain"] for row in rows]


def fetch(
    agent_id: AgentId | None = None,
    domain: str | None = None,
    spawn_id: SpawnId | None = None,
    decision_id: DecisionId | None = None,
    include_archived: bool = False,
    limit: int | None = None,
    project_id: ProjectId | None = None,
) -> list[Insight]:
    with store.ensure() as conn:
        query = store.q("insights").not_deleted()
        if not include_archived:
            query = query.not_archived()
        query = query.where_if("project_id = ?", project_id)
        query = query.where_if("agent_id = ?", agent_id)
        query = query.where_if("spawn_id = ?", spawn_id)
        query = query.where_if("decision_id = ?", decision_id)
        if domain:
            if domain.endswith("/*"):
                prefix = domain[:-2]
                query = query.where("(domain = ? OR domain LIKE ?)", prefix, f"{prefix}/%")
            else:
                query = query.where_if("domain = ?", domain)
        return query.order("created_at DESC").limit(limit).fetch(conn, Insight)


def reassign(insight_id: InsightId, project_id: ProjectId) -> Insight:
    with store.write() as conn:
        cursor = conn.execute(
            "UPDATE insights SET project_id = ? WHERE id = ? AND deleted_at IS NULL",
            (project_id, insight_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Insight '{insight_id}' not found")
    return get(insight_id)


def archive(insight_id: InsightId, restore: bool = False) -> Insight:
    with store.write() as conn:
        if restore:
            cursor = conn.execute(
                "UPDATE insights SET archived_at = NULL WHERE id = ? AND deleted_at IS NULL",
                (insight_id,),
            )
        else:
            now = datetime.now(UTC).isoformat()
            cursor = conn.execute(
                "UPDATE insights SET archived_at = ? WHERE id = ? AND deleted_at IS NULL",
                (now, insight_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Insight '{insight_id}' not found")
    return get(insight_id)


def delete(insight_id: InsightId) -> None:
    artifacts.soft_delete("insights", insight_id, "Insight")


def validated_decision_ids(decision_ids: list[DecisionId]) -> set[DecisionId]:
    """Return subset of decision_ids that have at least one linked insight."""
    if not decision_ids:
        return set()
    placeholders = ",".join("?" * len(decision_ids))
    with store.ensure() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT decision_id FROM insights WHERE decision_id IN ({placeholders}) AND deleted_at IS NULL",  # noqa: S608
            decision_ids,
        ).fetchall()
    return {DecisionId(row["decision_id"]) for row in rows}


def fetch_by_decision_ids(decision_ids: list[DecisionId]) -> dict[DecisionId, list[Insight]]:
    """Batch fetch insights grouped by decision_id."""
    if not decision_ids:
        return {}
    placeholders = ",".join("?" * len(decision_ids))
    with store.ensure() as conn:
        rows = conn.execute(
            f"SELECT * FROM insights WHERE decision_id IN ({placeholders}) AND deleted_at IS NULL ORDER BY created_at",  # noqa: S608
            decision_ids,
        ).fetchall()
    result: dict[DecisionId, list[Insight]] = {did: [] for did in decision_ids}
    for row in rows:
        insight = store.from_row(row, Insight)
        if insight.decision_id:
            result[insight.decision_id].append(insight)
    return result


def count(include_archived: bool = False, project_id: ProjectId | None = None) -> int:
    with store.ensure() as conn:
        query = store.q("insights").not_deleted()
        if not include_archived:
            query = query.not_archived()
        return query.where_if("project_id = ?", project_id).count(conn)


def open_count() -> int:
    """Count open insights (unresolved questions)."""
    with store.ensure() as conn:
        return store.q("insights").active().where("open = 1").count(conn)


def fetch_open(project_id: ProjectId | None = None, limit: int | None = None) -> list[Insight]:
    """Fetch open insights (unresolved questions)."""
    with store.ensure() as conn:
        return (
            store.q("insights")
            .active()
            .where("open = 1")
            .where_if("project_id = ?", project_id)
            .order("created_at DESC")
            .limit(limit)
            .fetch(conn, Insight)
        )


def fetch_closed(project_id: ProjectId | None = None, limit: int | None = None) -> list[Insight]:
    """Fetch closed insights (resolved questions) via activity log."""
    with store.ensure() as conn:
        params: list[str | int] = []
        query = """
            SELECT i.* FROM insights i
            INNER JOIN activity a ON a.primitive = 'insight' AND a.primitive_id = i.id AND a.action = 'resolved'
            WHERE i.open = 0 AND i.deleted_at IS NULL AND i.archived_at IS NULL
        """

        if project_id:
            query += " AND i.project_id = ?"
            params.append(project_id)

        query += " ORDER BY a.created_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(query, params).fetchall()
    return [store.from_row(row, Insight) for row in rows]


def close(insight_id: InsightId, counterfactual: bool | None = None) -> Insight:
    """Close an open insight. Optionally record counterfactual (could single agent have found this?)."""
    with store.write() as conn:
        if counterfactual is not None:
            cursor = conn.execute(
                "UPDATE insights SET open = 0, counterfactual = ? WHERE id = ? AND deleted_at IS NULL",
                (1 if counterfactual else 0, insight_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE insights SET open = 0 WHERE id = ? AND deleted_at IS NULL",
                (insight_id,),
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Insight '{insight_id}' not found")
    return get(insight_id)


def agents_with_inbox(project_id: ProjectId | None = None) -> set[str]:
    """Return handles of agents with unresolved inbox items (single query)."""
    with store.ensure() as conn:
        if project_id:
            rows = conn.execute(
                """
                SELECT DISTINCT json_each.value as handle
                FROM insights i, json_each(i.mentions)
                WHERE i.deleted_at IS NULL
                  AND i.archived_at IS NULL
                  AND i.mentions IS NOT NULL
                  AND i.project_id = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM replies r
                    JOIN agents a ON r.author_id = a.id
                    WHERE r.parent_type = 'insight'
                      AND r.parent_id = i.id
                      AND a.handle = json_each.value
                      AND r.deleted_at IS NULL
                  )
                UNION
                SELECT DISTINCT json_each.value as handle
                FROM replies r, json_each(r.mentions)
                WHERE r.deleted_at IS NULL
                  AND r.mentions IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM replies r2
                    JOIN agents a ON r2.author_id = a.id
                    WHERE r2.parent_type = r.parent_type
                      AND r2.parent_id = r.parent_id
                      AND a.handle = json_each.value
                      AND r2.created_at > r.created_at
                      AND r2.deleted_at IS NULL
                  )
                """,
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT DISTINCT json_each.value as handle
                FROM insights i, json_each(i.mentions)
                WHERE i.deleted_at IS NULL
                  AND i.archived_at IS NULL
                  AND i.mentions IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM replies r
                    JOIN agents a ON r.author_id = a.id
                    WHERE r.parent_type = 'insight'
                      AND r.parent_id = i.id
                      AND a.handle = json_each.value
                      AND r.deleted_at IS NULL
                  )
                UNION
                SELECT DISTINCT json_each.value as handle
                FROM replies r, json_each(r.mentions)
                WHERE r.deleted_at IS NULL
                  AND r.mentions IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM replies r2
                    JOIN agents a ON r2.author_id = a.id
                    WHERE r2.parent_type = r.parent_type
                      AND r2.parent_id = r.parent_id
                      AND a.handle = json_each.value
                      AND r2.created_at > r.created_at
                      AND r2.deleted_at IS NULL
                  )
                """
            ).fetchall()
    return {row["handle"] for row in rows}


def has_unprocessed_stream() -> bool:
    """Check if there are unprocessed stream insights."""
    with store.ensure() as conn:
        count = conn.execute(
            """
            SELECT COUNT(*) as cnt
            FROM insights i
            WHERE i.domain = 'stream'
              AND i.deleted_at IS NULL
              AND i.archived_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM replies r
                WHERE r.parent_type = 'insight' AND r.parent_id = i.id AND r.deleted_at IS NULL
              )
            """
        ).fetchone()["cnt"]
        return count > 0


def fetch_domain_questions(
    exclude_agent_id: AgentId,
    domains: list[str],
    project_id: ProjectId | None = None,
    limit: int = 3,
) -> list[Insight]:
    """Fetch open questions by others in specified domains."""
    if not domains:
        return []

    with store.ensure() as conn:
        domain_conditions = " OR ".join(["domain LIKE ?" for _ in domains])
        params: list[str] = [f"{d}%" for d in domains]
        params.append(exclude_agent_id)

        query = f"""
            SELECT * FROM insights
            WHERE open = 1
            AND deleted_at IS NULL AND archived_at IS NULL
            AND ({domain_conditions})
            AND agent_id != ?
        """  # noqa: S608

        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)

        query += f" ORDER BY created_at DESC LIMIT {limit}"
        rows = conn.execute(query, params).fetchall()

    return [store.from_row(row, Insight) for row in rows]


def fetch_foundational(
    project_id: ProjectId | None = None,
    min_refs: int = 3,
    min_age_days: int = 0,
    max_age_days: int = 0,
    limit: int = 3,
) -> list[tuple[Insight, int]]:
    """Fetch highly referenced insights (foundational knowledge)."""
    with store.ensure() as conn:
        where_params: list[str | int] = [min_age_days]
        base_query = """
            SELECT i.*,
                (
                    SELECT COUNT(*) FROM replies r
                    WHERE r.parent_id = i.id AND r.parent_type = 'insight'
                ) + (
                    SELECT COUNT(*) FROM citations c
                    WHERE c.target_type = 'insight' AND c.target_short_id = substr(i.id, 1, 8)
                ) as total_refs
            FROM insights i
            WHERE i.deleted_at IS NULL AND i.archived_at IS NULL
              AND julianday('now') - julianday(i.created_at) >= ?
        """

        if max_age_days:
            base_query += " AND julianday('now') - julianday(i.created_at) <= ?"
            where_params.append(max_age_days)

        if project_id:
            base_query += " AND i.project_id = ?"
            where_params.append(project_id)

        query = f"""
            SELECT * FROM ({base_query}) sub
            WHERE total_refs >= ?
            ORDER BY total_refs DESC LIMIT {limit}
        """  # noqa: S608
        rows = conn.execute(query, [*where_params, min_refs]).fetchall()

    return [(store.from_row(row, Insight), row["total_refs"]) for row in rows]


def threads_with_new_replies(
    agent_id: AgentId,
    since: str,
    project_id: ProjectId | None = None,
    limit: int = 3,
) -> list[tuple[Insight, int, str]]:
    """Fetch agent's insights that have replies after a timestamp.

    Returns list of (insight, reply_count, last_reply_preview).
    """
    with store.ensure() as conn:
        query = (
            store.q("insights")
            .active()
            .where("agent_id = ?", agent_id)
            .where_if("project_id = ?", project_id)
            .order("created_at DESC")
            .limit(50)
        )
        insight_rows = query.fetch(conn, Insight)

    if not insight_rows:
        return []

    all_replies = replies.fetch_for_parents("insight", [i.id for i in insight_rows])

    result: list[tuple[Insight, int, str]] = []
    for insight in insight_rows:
        thread_replies = all_replies.get(insight.id, [])
        new_replies = sorted(
            [r for r in thread_replies if r.created_at > since and r.author_id != agent_id],
            key=lambda r: r.created_at,
            reverse=True,
        )
        if new_replies:
            result.append((insight, len(new_replies), new_replies[0].content[:40]))
            if len(result) >= limit:
                break

    return result


def prune_stale_status(days: int = 3) -> int:
    """Archive old status domain insights that haven't been cited."""
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    now = datetime.now(UTC).isoformat()

    with store.write() as conn:
        cursor = conn.execute(
            """
            UPDATE insights SET archived_at = ?
            WHERE id IN (
                SELECT i.id FROM insights i
                WHERE i.deleted_at IS NULL
                  AND i.archived_at IS NULL
                  AND i.created_at < ?
                  AND (i.domain = 'status' OR i.domain LIKE 'status/%')
                  AND NOT EXISTS (
                    SELECT 1 FROM citations c
                    WHERE c.target_type = 'insight'
                      AND c.target_short_id = substr(i.id, 1, 8)
                  )
            )
            """,
            (now, cutoff),
        )
        return cursor.rowcount


def find_similar(
    content: str,
    exclude_id: InsightId | None = None,
    limit: int = 3,
) -> list[Insight]:
    """Find similar insights via FTS5 matching."""
    terms = nlp.extract_terms(content)
    if not terms:
        return []

    fts_query = " OR ".join(f'"{t}"' for t in terms)

    with store.ensure() as conn:
        sql = """
            SELECT i.* FROM insights i
            WHERE i.id IN (
                SELECT id FROM insights_fts WHERE insights_fts MATCH ?
            )
            AND i.deleted_at IS NULL AND i.archived_at IS NULL
        """
        params: list[str] = [fts_query]

        if exclude_id:
            sql += " AND i.id != ?"
            params.append(exclude_id)

        sql += " ORDER BY i.created_at DESC LIMIT ?"
        params.append(str(limit))

        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            return []

    return [store.from_row(row, Insight) for row in rows]
