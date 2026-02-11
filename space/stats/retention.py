from typing import Any

from space.core.types import ProjectId
from space.lib import store


def merge_rate(project_id: ProjectId | None = None, days: int = 30) -> dict[str, Any]:
    """PR merge rate: swarm-opened PRs vs customer-merged.
    
    Success = % PRs opened that get merged blind (no swarm author merging their own).
    """
    where_project = "AND pr.project_id = ?" if project_id else ""
    params = ([project_id] if project_id else []) + [f"-{days}"]
    
    with store.ensure() as conn:
        result = conn.execute(
            f"""
            SELECT
                COUNT(DISTINCT CASE WHEN pr.event_type = 'opened' THEN pr.pr_number END) as opened,
                COUNT(DISTINCT CASE WHEN pr.event_type = 'merged'
                    AND pr.merged_by != pr.author THEN pr.pr_number END) as merged_blind
            FROM pr_events pr
            WHERE pr.created_at > datetime('now', ? || ' days')
                {where_project}
            """,
            params,
        ).fetchone()
    
    opened = result[0]
    merged = result[1]
    rate = round(merged / opened * 100, 1) if opened else 0
    
    return {
        "days": days,
        "opened": opened,
        "merged_blind": merged,
        "rate": rate,
        "project_id": project_id,
    }


def engagement_per_project(days: int = 7) -> list[dict[str, Any]]:
    """Spawns/day per customer project.
    
    Measures swarm activity per customer repo.
    """
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id,
                p.name,
                COUNT(s.id) as spawns,
                ROUND(CAST(COUNT(s.id) AS FLOAT) / ?, 1) as spawns_per_day
            FROM projects p
            LEFT JOIN spawns s ON s.created_at > datetime('now', ? || ' days')
            WHERE p.type = 'customer' AND p.archived_at IS NULL
            GROUP BY p.id
            HAVING spawns > 0
            ORDER BY spawns_per_day DESC
            """,
            (days, f"-{days}"),
        ).fetchall()
    
    return [
        {
            "project_id": r[0],
            "project_name": r[1],
            "spawns": r[2],
            "spawns_per_day": r[3],
        }
        for r in rows
    ]


def compounding_delta(project_id: ProjectId, baseline_day: int = 1, target_day: int = 30) -> dict[str, Any]:
    """Quality score delta: day 1 vs day 30.
    
    Validates ledger accumulation = better output over time.
    Requires health_metrics per project.
    """
    with store.ensure() as conn:
        baseline_row = conn.execute(
            """
            SELECT score FROM health_metrics
            WHERE project_id = ?
              AND created_at >= datetime('now', ? || ' days')
              AND created_at < datetime('now', ? || ' days')
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (project_id, f"-{baseline_day + 1}", f"-{baseline_day}"),
        ).fetchone()
        
        target_row = conn.execute(
            """
            SELECT score FROM health_metrics
            WHERE project_id = ?
              AND created_at >= datetime('now', ? || ' days')
              AND created_at < datetime('now', ? || ' days')
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (project_id, f"-{target_day + 1}", f"-{target_day}"),
        ).fetchone()
    
    baseline = baseline_row[0] if baseline_row else None
    target = target_row[0] if target_row else None
    delta = target - baseline if (baseline is not None and target is not None) else None
    
    return {
        "project_id": project_id,
        "baseline_day": baseline_day,
        "target_day": target_day,
        "baseline_score": baseline,
        "target_score": target,
        "delta": delta,
    }


def summary(project_id: ProjectId | None = None) -> dict[str, Any]:
    """Retention proof dashboard: merge rate + compounding + engagement."""
    merge_data = merge_rate(project_id, days=30)
    engagement_data = engagement_per_project(days=7) if not project_id else []
    
    compound = {}
    if project_id:
        compound = compounding_delta(project_id, baseline_day=1, target_day=30)
    
    return {
        "merge_rate": merge_data,
        "engagement": engagement_data,
        "compounding": compound if compound else None,
    }
