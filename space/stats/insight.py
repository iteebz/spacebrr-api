from space.core.types import ProjectId
from space.lib import store


def reference_rate(hours: int = 168) -> float:
    with store.ensure() as conn:
        total = conn.execute(
            """
            SELECT COUNT(*) FROM insights
            WHERE deleted_at IS NULL AND archived_at IS NULL
              AND created_at > datetime('now', ? || ' hours')
            """,
            (f"-{hours}",),
        ).fetchone()[0]
        if not total:
            return 0.0
        refs = conn.execute(
            """
            SELECT COUNT(DISTINCT i.id) FROM insights i
            JOIN citations c ON c.source_type = 'insight' AND c.source_id = i.id
            WHERE i.deleted_at IS NULL AND i.archived_at IS NULL
              AND i.created_at > datetime('now', ? || ' hours')
            """,
            (f"-{hours}",),
        ).fetchone()[0]
        return round(refs / total * 100, 1)


def decision_insight_reference_rate(hours: int = 168) -> float:
    with store.ensure() as conn:
        total = conn.execute(
            """
            SELECT COUNT(*) FROM decisions
            WHERE deleted_at IS NULL
              AND created_at > datetime('now', ? || ' hours')
            """,
            (f"-{hours}",),
        ).fetchone()[0]
        if not total:
            return 0.0
        refs = conn.execute(
            """
            SELECT COUNT(DISTINCT d.id) FROM decisions d
            JOIN citations c ON c.source_type = 'decision' AND c.source_id = d.id
            WHERE d.deleted_at IS NULL
              AND d.created_at > datetime('now', ? || ' hours')
              AND c.target_type = 'insight'
            """,
            (f"-{hours}",),
        ).fetchone()[0]
        return round(refs / total * 100, 1)


def provenance_stats(project_id: ProjectId | None = None) -> dict[str, int]:
    with store.ensure() as conn:
        params: list[str] = []
        query = """
            SELECT provenance, COUNT(*) as cnt FROM insights
            WHERE deleted_at IS NULL AND archived_at IS NULL AND provenance IS NOT NULL
        """
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " GROUP BY provenance"
        rows = conn.execute(query, params).fetchall()
    return {row["provenance"]: row["cnt"] for row in rows}


def counterfactual_stats(project_id: ProjectId | None = None) -> dict[str, int]:
    with store.ensure() as conn:
        params: list[str] = []
        query = """
            SELECT
                SUM(CASE WHEN counterfactual = 1 THEN 1 ELSE 0 END) as solo_possible,
                SUM(CASE WHEN counterfactual = 0 THEN 1 ELSE 0 END) as swarm_required,
                SUM(CASE WHEN counterfactual IS NULL THEN 1 ELSE 0 END) as untagged
            FROM insights
            WHERE deleted_at IS NULL AND open = 0
        """
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        row = conn.execute(query, params).fetchone()
    return {
        "solo_possible": row["solo_possible"] or 0,
        "swarm_required": row["swarm_required"] or 0,
        "untagged": row["untagged"] or 0,
    }
