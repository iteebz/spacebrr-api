from typing import Any

from space import agents
from space.ledger import decisions, insights
from space.lib import store

from .decision import flow as decisions_flow
from .decision import precision as decisions_precision
from . import retention
from .swarm import absence_metrics, artifacts_per_spawn, live, loop_frequency, status


def public_payload() -> dict[str, Any]:
    live_data = live()
    swarm_status = status(hours=24)
    flow = decisions_flow()
    recent = decisions.fetch(limit=5)
    absence = absence_metrics(hours=168)

    agent_ids = list({d.agent_id for d in recent})
    agent_map = {a.id: a.handle for a in agents.batch_get(agent_ids).values()}

    agents_public = [
        {
            "handle": a["handle"],
            "health": a["health"],
            "status": a["status"],
            "artifact": a.get("artifact", "")[:60] if a.get("artifact") else None,
        }
        for a in live_data
    ]

    return {
        "agents": agents_public,
        "spawns_24h": swarm_status["spawns"],
        "insights_24h": swarm_status["insights"],
        "decisions": {
            "proposed": flow.get("proposed", 0),
            "committed": flow.get("committed", 0),
            "actioned": flow.get("actioned", 0),
            "recent": [
                {
                    "id": d.id[:8],
                    "title": d.content[:60],
                    "by": agent_map.get(d.agent_id, "unknown"),
                }
                for d in recent
            ],
        },
        "open_questions": len(swarm_status["open_questions"]),
        "absence": {
            "autonomy": absence["completion_autonomy"],
            "io_ratio": absence["input_output_ratio"],
            "block_hours": absence["block_duration_hours"],
        },
    }


def actionable_payload() -> dict[str, Any]:
    committed = decisions.fetch_by_status("committed")
    questions = insights.fetch_open(limit=10)

    all_agent_ids = list({d.agent_id for d in committed} | {q.agent_id for q in questions})
    agent_map = {a.id: a.handle for a in agents.batch_get(all_agent_ids).values()}
    return {
        "committed_decisions": len(committed),
        "committed": [
            {
                "id": d.id,
                "content": d.content,
                "handle": agent_map.get(d.agent_id, "unknown"),
                "created_at": d.created_at,
            }
            for d in committed
        ],
        "open_questions": len(questions),
        "questions": [
            {
                "id": q.id,
                "content": q.content,
                "handle": agent_map.get(q.agent_id, "unknown"),
                "domain": q.domain,
                "created_at": q.created_at,
            }
            for q in questions
        ],
    }


def health_payload(hours: int = 24) -> dict[str, Any]:
    loop = loop_frequency(hours)
    artifacts = artifacts_per_spawn(hours)
    flow = decisions_flow()
    precision = decisions_precision()

    total_spawns = sum(a["spawns"] for a in artifacts) if artifacts else 0
    avg_productivity = (
        round(sum(a["ratio"] for a in artifacts) / len(artifacts), 1) if artifacts else 0
    )

    rejection_rate = 0.0
    if precision["overall"]["actioned"] + precision["overall"]["rejected"] > 0:
        rejection_rate = round(
            precision["overall"]["rejected"]
            / (precision["overall"]["actioned"] + precision["overall"]["rejected"])
            * 100,
            1,
        )

    status = "healthy"
    issues: list[str] = []

    schema_drift: list[str] = []
    try:
        with store.existing() as conn:
            schema_drift = store.check_schema_drift(conn)
    except Exception as exc:
        status = "warning"
        issues.append(f"db check failed: {exc}")

    if schema_drift:
        status = "warning"
        issues.append(f"schema drift: {len(schema_drift)} issue(s)")

    if loop["max_consecutive"] >= 5:
        status = "warning"
        issues.append(f"loop detected: {loop['agent']} ({loop['max_consecutive']} consecutive)")

    if rejection_rate > 30:
        status = "warning"
        issues.append(f"high rejection rate: {rejection_rate}%")

    if avg_productivity < 2:
        status = "warning"
        issues.append(f"low productivity: {avg_productivity} artifacts/spawn")

    return {
        "status": status,
        "issues": issues,
        "spawns": total_spawns,
        "productivity": avg_productivity,
        "decisions_actioned": flow.get("actioned", 0),
        "decisions_rejected": flow.get("rejected", 0),
        "rejection_rate": rejection_rate,
        "loop_max": loop["max_consecutive"],
        "schema_drift": schema_drift,
    }


def retention_payload(project_id: str | None = None) -> dict[str, Any]:
    return retention.summary(project_id)


def colony_payload(hours: int = 24) -> dict[str, Any]:
    ai_agents = agents.fetch(type="ai")
    with store.existing() as conn:
        active_agent_ids = conn.execute(
            """
            SELECT DISTINCT agent_id FROM spawns
            WHERE status = 'active' AND created_at > datetime('now', '-1 hour')
            """
        ).fetchall()
        active_set = {r[0] for r in active_agent_ids}

        coordination = conn.execute(
            """
            SELECT r.author_id as from_id,
                   COALESCE(r2.author_id, d.agent_id, i.agent_id) as to_id,
                   r.parent_type
            FROM replies r
            LEFT JOIN replies r2 ON r.parent_type = 'reply' AND r.parent_id = r2.id
            LEFT JOIN decisions d ON r.parent_type = 'decision' AND r.parent_id = d.id
            LEFT JOIN insights i ON r.parent_type = 'insight' AND r.parent_id = i.id
            WHERE r.created_at > datetime('now', ? || ' hours')
              AND r.deleted_at IS NULL
            ORDER BY r.created_at DESC
            LIMIT 20
            """,
            (f"-{hours}",),
        ).fetchall()

        committed_count = conn.execute(
            """
            SELECT COUNT(*) FROM decisions
            WHERE committed_at IS NOT NULL
              AND rejected_at IS NULL
              AND actioned_at IS NULL
              AND deleted_at IS NULL
              AND archived_at IS NULL
            """
        ).fetchone()[0]

        insight_count = conn.execute(
            """
            SELECT COUNT(*) FROM insights
            WHERE deleted_at IS NULL AND archived_at IS NULL
            """
        ).fetchone()[0]

    colonists = [
        {"id": a.id, "handle": a.handle, "active": a.id in active_set}
        for a in ai_agents
        if not a.archived_at
    ]

    agent_id_map = {a.id: a.id for a in ai_agents}
    arcs = []
    seen = set()
    for from_id, to_id, parent_type in coordination:
        if not from_id or not to_id or from_id == to_id:
            continue
        if from_id not in agent_id_map or to_id not in agent_id_map:
            continue
        key = (from_id, to_id)
        if key in seen:
            continue
        seen.add(key)
        arc_type = "decision" if parent_type == "decision" else "reply"
        arcs.append({"from": from_id, "to": to_id, "type": arc_type})

    return {
        "colonists": colonists,
        "arcs": arcs[:10],
        "structures": min(committed_count, 12),
        "research": min(insight_count // 10, 8),
    }
