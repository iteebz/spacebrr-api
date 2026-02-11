from typing import Any

from space.lib import store


def flow() -> dict[str, int]:
    """Decision status breakdown."""
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                CASE
                    WHEN rejected_at IS NOT NULL THEN 'rejected'
                    WHEN actioned_at IS NOT NULL THEN 'actioned'
                    ELSE 'committed'
                END as status,
                COUNT(*) as count
            FROM decisions
            WHERE deleted_at IS NULL AND archived_at IS NULL
            GROUP BY status
            """
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def reversal_rate() -> dict[str, Any]:
    """Committed decisions later rejected. Measures premature commitment.

    Categorizes reversals by analyzing rejection rationale in replies:
    - error: agent was wrong (flawed logic, incorrect assessment)
    - obsolete: conditions changed (superseded, no longer relevant)
    - unclear: no rationale or ambiguous
    """
    with store.ensure() as conn:
        total_committed = conn.execute(
            """
            SELECT COUNT(*) FROM decisions
            WHERE committed_at IS NOT NULL AND deleted_at IS NULL
            """
        ).fetchone()[0]

        reversed = conn.execute(
            """
            SELECT d.id, d.rejected_at
            FROM decisions d
            WHERE d.committed_at IS NOT NULL
              AND d.rejected_at IS NOT NULL
              AND d.deleted_at IS NULL
            """
        ).fetchall()

    error_count = 0
    obsolete_count = 0
    unclear_count = 0

    error_signals = ["wrong", "incorrect", "flawed", "mistake", "broken", "error", "bad"]
    obsolete_signals = [
        "superseded",
        "obsolete",
        "changed",
        "conditions",
        "no longer",
        "deprecated",
    ]

    with store.ensure() as conn:
        for decision_id, rejected_at in reversed:
            reply = conn.execute(
                """
                SELECT content FROM replies
                WHERE parent_type = 'decision'
                  AND parent_id = ?
                  AND created_at >= ?
                  AND deleted_at IS NULL
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (decision_id, rejected_at),
            ).fetchone()

            if not reply or not reply[0]:
                unclear_count += 1
                continue

            content_lower = reply[0].lower()

            if any(sig in content_lower for sig in error_signals):
                error_count += 1
            elif any(sig in content_lower for sig in obsolete_signals):
                obsolete_count += 1
            else:
                unclear_count += 1

    reversed_count = len(reversed)
    rate = round(reversed_count / total_committed * 100, 1) if total_committed else 0

    return {
        "total_committed": total_committed,
        "reversed": reversed_count,
        "reversal_rate": rate,
        "by_category": {
            "error": error_count,
            "obsolete": obsolete_count,
            "unclear": unclear_count,
        },
    }


def half_life() -> dict[str, Any]:
    """Median time from committed to actioned. Decision velocity."""
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                (julianday(actioned_at) - julianday(committed_at)) * 24 as hours
            FROM decisions
            WHERE committed_at IS NOT NULL AND actioned_at IS NOT NULL
              AND deleted_at IS NULL
            ORDER BY hours
            """
        ).fetchall()

    if not rows:
        return {"sample_size": 0, "median_hours": None, "p25_hours": None, "p75_hours": None}

    hours_list = [r[0] for r in rows]
    n = len(hours_list)
    median = hours_list[n // 2] if n % 2 else (hours_list[n // 2 - 1] + hours_list[n // 2]) / 2
    p25 = hours_list[n // 4]
    p75 = hours_list[3 * n // 4]

    return {
        "sample_size": n,
        "median_hours": round(median, 1),
        "p25_hours": round(p25, 1),
        "p75_hours": round(p75, 1),
    }


def influence() -> dict[str, Any]:
    """Measure which decisions get referenced (via citations table + FK links)."""
    with store.ensure() as conn:
        total_decisions = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE deleted_at IS NULL"
        ).fetchone()[0]

        citation_refs = conn.execute(
            """
            SELECT target_short_id, COUNT(*) as ref_count
            FROM citations
            WHERE target_type = 'decision'
            GROUP BY target_short_id
            """
        ).fetchall()

        fk_linked = conn.execute(
            """
            SELECT DISTINCT SUBSTR(decision_id, 1, 8) FROM tasks
            WHERE decision_id IS NOT NULL AND deleted_at IS NULL
            UNION
            SELECT DISTINCT SUBSTR(decision_id, 1, 8) FROM insights
            WHERE decision_id IS NOT NULL AND deleted_at IS NULL
            """
        ).fetchall()

    refs: dict[str, int] = {row[0]: row[1] for row in citation_refs}

    for (prefix,) in fk_linked:
        if prefix:
            refs[prefix] = refs.get(prefix, 0) + 1

    referenced_decisions = len(refs)
    total_refs = sum(refs.values())
    influence_rate = (
        round(referenced_decisions / total_decisions * 100, 1) if total_decisions else 0
    )
    top_decisions = sorted(refs.items(), key=lambda x: -x[1])[:5]

    return {
        "total_decisions": total_decisions,
        "referenced": referenced_decisions,
        "total_refs": total_refs,
        "influence_rate": influence_rate,
        "top": top_decisions,
    }


def precision() -> dict[str, Any]:
    """Measure decision acceptance rate by agent."""
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                a.handle,
                SUM(CASE WHEN d.actioned_at IS NOT NULL THEN 1 ELSE 0 END) as actioned,
                SUM(CASE WHEN d.rejected_at IS NOT NULL THEN 1 ELSE 0 END) as rejected,
                COUNT(*) as total
            FROM decisions d
            JOIN agents a ON d.agent_id = a.id
            WHERE d.deleted_at IS NULL
              AND LOWER(d.content) NOT LIKE '%test%'
              AND LOWER(d.rationale) NOT LIKE '%test%'
            GROUP BY a.handle
            HAVING total >= 5
            ORDER BY total DESC
            """
        ).fetchall()

    by_agent = []
    for handle, actioned, rejected, total in rows:
        closed = actioned + rejected
        precision_rate = round(actioned / closed * 100, 1) if closed else None
        by_agent.append(
            {
                "agent": handle,
                "actioned": actioned,
                "rejected": rejected,
                "total": total,
                "precision": precision_rate,
            }
        )

    total_actioned = sum(r["actioned"] for r in by_agent)
    total_rejected = sum(r["rejected"] for r in by_agent)
    total_closed = total_actioned + total_rejected
    overall_precision = round(total_actioned / total_closed * 100, 1) if total_closed else 0

    return {
        "by_agent": by_agent,
        "overall": {
            "actioned": total_actioned,
            "rejected": total_rejected,
            "precision": overall_precision,
        },
    }


def challenge_rate() -> dict[str, Any]:
    """Measure decisions receiving dissent before commit.

    Challenge = reply from different agent between created_at and committed_at.
    Per arxiv paper: adversarial oversight metric for constitutional orthogonality.
    """
    with store.ensure() as conn:
        total_committed = conn.execute(
            """
            SELECT COUNT(*) FROM decisions
            WHERE committed_at IS NOT NULL AND deleted_at IS NULL
            """
        ).fetchone()[0]

        challenged = conn.execute(
            """
            SELECT COUNT(DISTINCT d.id)
            FROM decisions d
            JOIN replies r ON r.parent_type = 'decision' AND r.parent_id = d.id
            WHERE d.committed_at IS NOT NULL
              AND d.deleted_at IS NULL
              AND r.deleted_at IS NULL
              AND r.author_id != d.agent_id
              AND r.created_at < d.committed_at
            """
        ).fetchone()[0]

    rate = round(challenged / total_committed * 100, 1) if total_committed else 0
    return {
        "total_committed": total_committed,
        "challenged": challenged,
        "challenge_rate": rate,
    }
