from datetime import datetime
from typing import Any

from space import agents
from space.ledger import insights
from space.lib import store


def artifacts_per_spawn(hours: int = 24) -> list[dict[str, Any]]:
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                a.handle,
                COUNT(DISTINCT act.spawn_id) as spawn_count,
                COUNT(act.id) as artifact_count,
                ROUND(CAST(COUNT(act.id) AS FLOAT) / NULLIF(COUNT(DISTINCT act.spawn_id), 0), 2) as ratio
            FROM activity act
            JOIN agents a ON act.agent_id = a.id
            WHERE act.spawn_id IS NOT NULL
              AND act.created_at > datetime('now', ? || ' hours')
              AND act.action = 'created'
            GROUP BY a.handle
            ORDER BY ratio DESC
            """,
            (f"-{hours}",),
        ).fetchall()
    return [{"agent": r[0], "spawns": r[1], "artifacts": r[2], "ratio": r[3]} for r in rows]


def loop_frequency(hours: int = 24) -> dict[str, Any]:
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT agent_id, created_at
            FROM spawns
            WHERE created_at > datetime('now', ? || ' hours')
            ORDER BY created_at
            """,
            (f"-{hours}",),
        ).fetchall()

    if not rows:
        return {"max_consecutive": 0, "agent": None}

    max_consecutive = 1
    max_agent = None
    current_consecutive = 1
    prev_agent = rows[0][0] if rows else None

    for agent_id, _ in rows[1:]:
        if agent_id == prev_agent:
            current_consecutive += 1
            if current_consecutive > max_consecutive:
                max_consecutive = current_consecutive
                max_agent = prev_agent
        else:
            current_consecutive = 1
        prev_agent = agent_id

    agent_name = None
    if max_agent:
        with store.ensure() as conn:
            row = conn.execute("SELECT handle FROM agents WHERE id = ?", (max_agent,)).fetchone()
            agent_name = row[0] if row else max_agent[:8]

    return {"max_consecutive": max_consecutive, "agent": agent_name}


def engagement(hours: int = 24) -> list[dict[str, Any]]:
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                a.handle,
                SUM(CASE WHEN act.primitive = 'insight' THEN 1 ELSE 0 END) as insights,
                SUM(CASE WHEN act.primitive = 'reply' THEN 1 ELSE 0 END) as replies,
                ROUND(
                    CAST(SUM(CASE WHEN act.primitive = 'reply' THEN 1 ELSE 0 END) AS FLOAT) /
                    NULLIF(SUM(CASE WHEN act.primitive = 'insight' THEN 1 ELSE 0 END), 0),
                    2
                ) as ratio
            FROM activity act
            JOIN agents a ON act.agent_id = a.id
            WHERE act.created_at > datetime('now', ? || ' hours')
              AND act.action = 'created'
              AND act.primitive IN ('insight', 'reply')
            GROUP BY a.handle
            HAVING insights > 0 OR replies > 0
            ORDER BY ratio DESC NULLS LAST
            """,
            (f"-{hours}",),
        ).fetchall()
    return [{"agent": r[0], "insights": r[1], "replies": r[2], "ratio": r[3]} for r in rows]


def compounding(hours: int = 168) -> dict[str, Any]:
    with store.ensure() as conn:
        window_total = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM insights
                 WHERE deleted_at IS NULL AND archived_at IS NULL
                   AND created_at > datetime('now', ? || ' hours'))
                +
                (SELECT COUNT(*) FROM decisions
                 WHERE deleted_at IS NULL AND archived_at IS NULL
                   AND created_at > datetime('now', ? || ' hours'))
            """,
            (f"-{hours}", f"-{hours}"),
        ).fetchone()[0]

        window_referencing = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT DISTINCT i.id FROM insights i
                JOIN citations c ON c.source_type = 'insight' AND c.source_id = i.id
                WHERE i.deleted_at IS NULL AND i.archived_at IS NULL
                  AND i.created_at > datetime('now', ? || ' hours')
                UNION
                SELECT DISTINCT d.id FROM decisions d
                JOIN citations c ON c.source_type = 'decision' AND c.source_id = d.id
                WHERE d.deleted_at IS NULL AND d.archived_at IS NULL
                  AND d.created_at > datetime('now', ? || ' hours')
            )
            """,
            (f"-{hours}", f"-{hours}"),
        ).fetchone()[0]

        by_agent = conn.execute(
            """
            SELECT handle, SUM(total) as total, SUM(refs) as refs FROM (
                SELECT
                    a.handle,
                    COUNT(DISTINCT i.id) as total,
                    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL THEN i.id END) as refs
                FROM insights i
                JOIN agents a ON i.agent_id = a.id
                LEFT JOIN citations c ON c.source_type = 'insight' AND c.source_id = i.id
                WHERE i.deleted_at IS NULL AND i.archived_at IS NULL
                  AND i.created_at > datetime('now', ? || ' hours')
                GROUP BY a.handle
                UNION ALL
                SELECT
                    a.handle,
                    COUNT(DISTINCT d.id) as total,
                    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL THEN d.id END) as refs
                FROM decisions d
                JOIN agents a ON d.agent_id = a.id
                LEFT JOIN citations c ON c.source_type = 'decision' AND c.source_id = d.id
                WHERE d.deleted_at IS NULL AND d.archived_at IS NULL
                  AND d.created_at > datetime('now', ? || ' hours')
                GROUP BY a.handle
            )
            GROUP BY handle
            HAVING total >= 3
            ORDER BY refs DESC
            """,
            (f"-{hours}", f"-{hours}"),
        ).fetchall()

    rate = round(window_referencing / window_total * 100, 1) if window_total else 0
    return {
        "window_hours": hours,
        "total": window_total,
        "referencing": window_referencing,
        "rate": rate,
        "by_agent": [
            {
                "agent": r[0],
                "total": r[1],
                "refs": r[2],
                "rate": round(r[2] / r[1] * 100, 1) if r[1] else 0,
            }
            for r in by_agent
        ],
    }


def task_sovereignty(hours: int = 168) -> dict[str, Any]:
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                a.handle,
                COUNT(CASE WHEN t.creator_id = t.assignee_id THEN 1 END) as self_created,
                COUNT(CASE WHEN t.creator_id != t.assignee_id OR t.creator_id IS NULL THEN 1 END) as assigned,
                COUNT(*) as total
            FROM tasks t
            JOIN agents a ON t.assignee_id = a.id
            WHERE t.deleted_at IS NULL
              AND t.created_at > datetime('now', ? || ' hours')
            GROUP BY a.handle
            HAVING total >= 3
            ORDER BY total DESC
            """,
            (f"-{hours}",),
        ).fetchall()

        totals = conn.execute(
            """
            SELECT
                COUNT(CASE WHEN t.creator_id = t.assignee_id THEN 1 END) as self_created,
                COUNT(*) as total
            FROM tasks t
            WHERE t.deleted_at IS NULL
              AND t.created_at > datetime('now', ? || ' hours')
            """,
            (f"-{hours}",),
        ).fetchone()

    overall_rate = round(totals[0] / totals[1] * 100, 0) if totals[1] else 0
    return {
        "window_hours": hours,
        "overall_rate": overall_rate,
        "self_created": totals[0],
        "total": totals[1],
        "by_agent": [
            {
                "agent": r[0],
                "self_created": r[1],
                "assigned": r[2],
                "total": r[3],
                "rate": round(r[1] / r[3] * 100, 0) if r[3] else 0,
            }
            for r in rows
        ],
    }


def knowledge_decay(weeks: int = 12) -> dict[str, Any]:
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                CAST((julianday('now') - julianday(i.created_at)) / 7 AS INTEGER) as week_age,
                COUNT(DISTINCT i.id) as total,
                COUNT(c.id) as citations
            FROM insights i
            LEFT JOIN citations c ON c.target_type = 'insight'
                AND c.target_short_id = substr(i.id, 1, 8)
            WHERE i.deleted_at IS NULL AND i.archived_at IS NULL
            GROUP BY week_age
            HAVING week_age IS NOT NULL AND week_age < ?
            ORDER BY week_age
            """,
            (weeks,),
        ).fetchall()

    buckets = []
    for r in rows:
        rate = round(r[2] / r[1], 2) if r[1] else 0
        buckets.append({"week": r[0], "total": r[1], "citations": r[2], "rate": rate})
    return {"weeks": weeks, "buckets": buckets}


def project_distribution(hours: int = 24) -> dict[str, Any]:
    with store.ensure() as conn:
        total = conn.execute(
            """
            SELECT
                COUNT(*) as spawn_count,
                COUNT(DISTINCT agent_id) as unique_agents
            FROM spawns
            WHERE created_at > datetime('now', ? || ' hours')
            """,
            (f"-{hours}",),
        ).fetchone()

    return {
        "hours": hours,
        "total": total[0],
        "unique_agents": total[1],
    }


def status(hours: int = 24) -> dict[str, Any]:
    with store.ensure() as conn:
        spawn_count = conn.execute(
            "SELECT COUNT(*) FROM spawns WHERE created_at > datetime('now', ? || ' hours')",
            (f"-{hours}",),
        ).fetchone()[0]

        insight_count = conn.execute(
            "SELECT COUNT(*) FROM insights WHERE created_at > datetime('now', ? || ' hours') AND deleted_at IS NULL",
            (f"-{hours}",),
        ).fetchone()[0]

        decision_stats = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN actioned_at IS NOT NULL THEN 1 ELSE 0 END) as actioned,
                SUM(CASE WHEN rejected_at IS NOT NULL THEN 1 ELSE 0 END) as rejected
            FROM decisions
            WHERE created_at > datetime('now', ? || ' hours') AND deleted_at IS NULL
            """,
            (f"-{hours}",),
        ).fetchone()

        recent_summaries = conn.execute(
            """
            SELECT DISTINCT substr(s.summary, 1, 200) as summary
            FROM spawns s
            WHERE s.summary IS NOT NULL
              AND s.summary <> ''
              AND s.created_at > datetime('now', ? || ' hours')
            ORDER BY s.created_at DESC
            LIMIT 10
            """,
            (f"-{hours}",),
        ).fetchall()

        open_q = conn.execute(
            """
            SELECT i.id, i.content, a.handle
            FROM insights i
            JOIN agents a ON i.agent_id = a.id
            WHERE i.open = 1 AND i.deleted_at IS NULL AND i.archived_at IS NULL
            ORDER BY i.created_at DESC
            LIMIT 5
            """,
        ).fetchall()

        unresolved_mentions = conn.execute(
            """
            SELECT COUNT(*) FROM replies
            WHERE content LIKE '%@human%'
              AND deleted_at IS NULL
              AND created_at > datetime('now', '-48 hours')
            """,
        ).fetchone()[0]

    silent = agents.metrics.silent_agents(hours)

    return {
        "hours": hours,
        "spawns": spawn_count,
        "insights": insight_count,
        "decisions": {
            "total": decision_stats[0],
            "actioned": decision_stats[1],
            "rejected": decision_stats[2],
        },
        "recent_summaries": [r[0] for r in recent_summaries],
        "open_questions": [{"id": r[0][:8], "content": r[1][:80], "agent": r[2]} for r in open_q],
        "unresolved_human_mentions": unresolved_mentions,
        "silent_agents": [s.handle for s in silent if (s.hours_silent or 0) > hours],
    }


def absence_metrics(hours: int = 168) -> dict[str, Any]:
    with store.ensure() as conn:
        human_ids = [
            r[0]
            for r in conn.execute(
                "SELECT id FROM agents WHERE type = 'human' AND deleted_at IS NULL"
            ).fetchall()
        ]
        if not human_ids:
            return {
                "block_duration_hours": 0,
                "completion_autonomy": 100.0,
                "input_output_ratio": 0,
                "human_inputs": 0,
                "swarm_outputs": 0,
            }

        placeholders = ",".join("?" * len(human_ids))

        human_replies = conn.execute(
            f"""
            SELECT COUNT(*) FROM replies
            WHERE author_id IN ({placeholders})
              AND created_at > datetime('now', ? || ' hours')
              AND deleted_at IS NULL
            """,  # noqa: S608
            [*human_ids, f"-{hours}"],
        ).fetchone()[0]

        human_decisions = conn.execute(
            f"""
            SELECT COUNT(*) FROM decisions
            WHERE agent_id IN ({placeholders})
              AND created_at > datetime('now', ? || ' hours')
              AND deleted_at IS NULL
            """,  # noqa: S608
            [*human_ids, f"-{hours}"],
        ).fetchone()[0]

        human_inputs = human_replies + human_decisions

        swarm_outputs = conn.execute(
            """
            SELECT COUNT(*) FROM activity
            WHERE action = 'created'
              AND created_at > datetime('now', ? || ' hours')
            """,
            (f"-{hours}",),
        ).fetchone()[0]

        io_ratio = round(human_inputs / swarm_outputs, 4) if swarm_outputs else 0

        mentions_with_response = conn.execute(
            f"""
            SELECT
                m.created_at as mention_time,
                MIN(r.created_at) as response_time
            FROM replies m
            JOIN replies r ON r.parent_type = m.parent_type
                          AND r.parent_id = m.parent_id
                          AND r.author_id IN ({placeholders})
                          AND r.created_at > m.created_at
            WHERE m.content LIKE '%@human%'
              AND m.created_at > datetime('now', ? || ' hours')
              AND m.deleted_at IS NULL
            GROUP BY m.id
            """,  # noqa: S608
            [*human_ids, f"-{hours}"],
        ).fetchall()

        if mentions_with_response:
            total_hours = 0
            for mention_time, response_time in mentions_with_response:
                mt = datetime.fromisoformat(mention_time)
                rt = datetime.fromisoformat(response_time)
                total_hours += (rt - mt).total_seconds() / 3600
            avg_block_hours = round(total_hours / len(mentions_with_response), 1)
        else:
            avg_block_hours = 0

        total_tasks = conn.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE completed_at IS NOT NULL
              AND created_at > datetime('now', ? || ' hours')
              AND deleted_at IS NULL
            """,
            (f"-{hours}",),
        ).fetchone()[0]

        human_touched_tasks = conn.execute(
            f"""
            SELECT COUNT(DISTINCT t.id) FROM tasks t
            JOIN replies r ON r.parent_type = 'task'
                          AND r.parent_id = t.id
                          AND r.author_id IN ({placeholders})
            WHERE t.completed_at IS NOT NULL
              AND t.created_at > datetime('now', ? || ' hours')
              AND t.deleted_at IS NULL
            """,  # noqa: S608
            [*human_ids, f"-{hours}"],
        ).fetchone()[0]

        autonomy = (
            round((total_tasks - human_touched_tasks) / total_tasks * 100, 1)
            if total_tasks
            else 100.0
        )

    return {
        "hours": hours,
        "block_duration_hours": avg_block_hours,
        "completion_autonomy": autonomy,
        "input_output_ratio": io_ratio,
        "human_inputs": human_inputs,
        "swarm_outputs": swarm_outputs,
        "tasks_total": total_tasks,
        "tasks_autonomous": total_tasks - human_touched_tasks,
    }


def silent_agents(hours: int = 24) -> list[dict[str, Any]]:
    result = agents.metrics.silent_agents(hours)
    return [
        {"handle": s.handle, "last_activity": s.last_activity, "hours_silent": s.hours_silent}
        for s in result
    ]


def open_questions() -> int:
    return insights.open_count()


def spawn_stats(limit: int = 10) -> list[dict[str, Any]]:
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                s.id,
                a.handle,
                s.created_at,
                s.last_active_at,
                s.status,
                s.summary,
                (SELECT COUNT(*) FROM activity act
                 WHERE act.spawn_id = s.id AND act.action = 'created') as artifacts,
                (SELECT COUNT(*) FROM activity act
                 WHERE act.spawn_id = s.id AND act.primitive = 'task'
                   AND act.action IN ('started', 'completed', 'claimed')) as task_transitions,
                (SELECT COUNT(*) FROM insights i WHERE i.spawn_id = s.id) as insights_created,
                (SELECT COUNT(*) FROM decisions d WHERE d.spawn_id = s.id) as decisions_created,
                (SELECT COUNT(*) FROM tasks t WHERE t.spawn_id = s.id) as tasks_created
            FROM spawns s
            JOIN agents a ON s.agent_id = a.id
            WHERE s.status = 'done'
            ORDER BY s.last_active_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result = []
    for r in rows:
        total = r[8] + r[9] + r[10]
        insight_only = total > 0 and r[9] == 0 and r[10] == 0
        result.append(
            {
                "id": r[0][:8],
                "handle": r[1],
                "created_at": r[2],
                "ended_at": r[3],
                "status": r[4],
                "summary": r[5],
                "artifacts": r[6],
                "task_transitions": r[7],
                "insights": r[8],
                "decisions": r[9],
                "tasks": r[10],
                "insight_only": insight_only,
            }
        )
    return result


def compounding_trend(weeks: int = 8, bucket_days: int = 7) -> dict[str, Any]:
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT
                CAST((julianday('now') - julianday(i.created_at)) / ? AS INTEGER) as bucket,
                COUNT(DISTINCT i.id) as total,
                COUNT(DISTINCT CASE WHEN c.id IS NOT NULL THEN i.id END) as referencing
            FROM insights i
            LEFT JOIN citations c ON c.source_type = 'insight' AND c.source_id = i.id
            WHERE i.deleted_at IS NULL AND i.archived_at IS NULL
              AND i.created_at > datetime('now', ? || ' days')
            GROUP BY bucket
            HAVING bucket IS NOT NULL
            ORDER BY bucket DESC
            """,
            (bucket_days, f"-{weeks * bucket_days}"),
        ).fetchall()

    buckets = []
    for r in rows:
        rate = round(r[2] / r[1] * 100, 1) if r[1] else 0
        buckets.append({"weeks_ago": r[0], "total": r[1], "referencing": r[2], "rate": rate})

    rates = [b["rate"] for b in buckets if b["total"] >= 3]
    trend = round(rates[0] - rates[-1], 1) if len(rates) >= 2 else 0

    return {"weeks": weeks, "bucket_days": bucket_days, "buckets": buckets, "trend": trend}
