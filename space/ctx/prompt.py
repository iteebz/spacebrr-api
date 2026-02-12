
from datetime import UTC, datetime

from space import agents
from space.agents import spawn
from space.core.models import Agent, Spawn, SpawnStatus
from space.ledger import decisions, insights, projects
from space.lib import store
from space.lib.display import format as format_mod

_CACHE_TTL = 300


def wake(spawn: Spawn, agent: Agent | None = None, skills: list[str] | None = None) -> str:
    agent = agent or agents.get(spawn.agent_id)

    parts = [
        _projects_block(spawn),
        _me_block(agent, spawn),
        _routines_block(),
    ]

    if skills:
        from space.ctx import skills as skills_mod  # noqa: PLC0415

        parts.append(skills_mod.inject(skills))

    parts.append("act.")
    return "\n\n".join(p for p in parts if p)


def resume(
    instruction: str = "continue",
    images: list[str] | None = None,
    spawn: Spawn | None = None,
    cwd: str | None = None,
) -> str:
    if not spawn:
        return instruction

    context = "continue working on the task" if instruction == "0" else instruction
    return f"<system-reminder>\nSession resumed.\n</system-reminder>\n\n{context}"


def _me_block(agent: Agent, current_spawn: Spawn) -> str:
    sections: list[str] = []

    summary_lines = _recent_summaries(agent, current_spawn)
    if summary_lines:
        sections.append("[spawns]\n" + "\n".join(summary_lines))

    my_insights = insights.fetch(agent_id=agent.id, limit=5)
    if my_insights:
        lines = [
            f"  {store.ref('insights', i.id)} [{i.domain or '?'}] {format_mod.truncate(i.content, 70, flatten=True)}"
            for i in my_insights
        ]
        sections.append("[insights]\n" + "\n".join(lines))

    my_decisions = decisions.fetch(agent_id=agent.id, limit=5)
    if my_decisions:
        lines = [
            f"  {store.ref('decisions', d.id)} [{'rejected' if d.rejected_at else 'actioned' if d.actioned_at else 'committed' if d.committed_at else 'proposed'}] {format_mod.truncate(d.content, 70, flatten=True)}"
            for d in my_decisions
        ]
        sections.append("[decisions]\n" + "\n".join(lines))

    if not sections:
        return ""
    body = "\n\n".join(sections)
    return f"<me>\n{body}\n</me>"


def _recent_summaries(agent: Agent, current_spawn: Spawn) -> list[str]:
    prior = spawn.fetch(
        agent_id=agent.id,
        status=SpawnStatus.DONE,
        limit=3,
    )
    return [_format_summary(s) for s in prior if s.summary and s.id != current_spawn.id]


def _format_summary(s) -> str:
    ts = _ago_str(getattr(s, "created_at", None) or getattr(s, "last_active_at", None))
    spawn_ref = store.ref("spawns", s.id)
    return f"{spawn_ref} ({ts}): {s.summary}"


def _ago_str(timestamp: str | None) -> str:
    if not timestamp:
        return "?"
    last = datetime.fromisoformat(timestamp)
    delta = datetime.now(UTC) - last
    hours = int(delta.total_seconds() // 3600)
    if hours < 1:
        return "<1h ago"
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _projects_block(spawn: Spawn) -> str:
    from space.lib import config  # noqa: PLC0415

    all_projects = projects.fetch()
    if not all_projects:
        return ""

    cfg = config.load()
    focus_project = cfg.swarm.project if cfg.swarm.enabled else None

    if focus_project:
        all_projects = [p for p in all_projects if p.name == focus_project]
        if not all_projects:
            return ""

    project_ids = [p.id for p in all_projects]
    last_active_map = projects.batch_last_active(project_ids)
    artifact_counts = projects.batch_artifact_counts(project_ids)

    sorted_projects = sorted(
        all_projects,
        key=lambda p: (last_active_map.get(p.id) or p.created_at or "", p.name),
        reverse=True,
    )

    lines = []
    for p in sorted_projects:
        count = artifact_counts.get(p.id, 0)
        last_active = last_active_map.get(p.id)
        activity = format_mod.ago(last_active) if last_active else "·"
        tags_str = f"  [{','.join(p.tags)}]" if p.tags else ""
        path_str = f"  {p.repo_path}" if p.repo_path else ""
        lines.append(f"{p.name:<15} {count:>4} {activity:>3}{tags_str}{path_str}")

    return f"<projects>\n{chr(10).join(lines)}\n</projects>"


def _routines_block() -> str:
    """Standing behaviors — playbooks that persist across spawn."""
    all_routines = insights.fetch(domain="routine", limit=50)
    routines = [r for r in all_routines if r.open]
    if not routines:
        return ""

    lines = [f"- {r.content}" for r in routines]
    return f"<routines>\n{'\n'.join(lines)}\n</routines>"
