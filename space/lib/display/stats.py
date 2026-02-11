from typing import Any

from space.lib.display.format import truncate


def format_me(summary: dict[str, Any], hours: int) -> str:
    lines = [f"[{hours}h window]", ""]

    artifacts = summary["artifacts_per_spawn"]
    lines.append("[artifacts/spawn]")
    lines.extend(f"  {row['agent']}: {row['ratio']} ({row['spawns']} spawns)" for row in artifacts)
    lines.append("")

    loop = summary["loop_frequency"]
    if loop["agent"]:
        lines.append(f"[loop] {loop['max_consecutive']} consecutive by {loop['agent']}")
    else:
        lines.append("[loop] 0 consecutive spawns")
    lines.append("")

    compounding = summary["compounding"]
    lines.append(f"[compounding] {compounding['rate']:.1f}% reference prior work")
    lines.append("")

    sovereignty = summary["task_sovereignty"]
    lines.append(
        f"[task sovereignty] {sovereignty['overall_rate']:.0f}% ({sovereignty['self_created']}/{sovereignty['total']} tasks self-created)"
    )
    lines.append("")

    decisions = summary["decision_flow"]
    if decisions:
        lines.append(
            f"[decisions] {decisions.get('actioned', 0)} actioned, {decisions.get('committed', 0)} committed, {decisions.get('rejected', 0)} rejected"
        )
    else:
        lines.append("[decisions] no activity")

    return "\n".join(lines)


def format_status(data: dict[str, Any], hours: int) -> str:
    lines = [f"[OVERNIGHT] ({hours}h)"]
    lines.append(f"  {data['spawns']} spawns, {data['insights']} insights")
    d = data["decisions"]
    lines.append(f"  {d['total']} decisions ({d['actioned']} actioned, {d['rejected']} rejected)")

    if data["recent_summaries"]:
        lines.append("\n[RECENT WORK]")
        lines.extend(
            f"  - {truncate(summary.split('\n')[0])}" for summary in data["recent_summaries"][:5]
        )

    if data["open_questions"]:
        lines.append(f"\n[OPEN QUESTIONS] ({len(data['open_questions'])})")
        lines.extend(
            f"  [{q['agent']}] {truncate(q['content'])}" for q in data["open_questions"][:3]
        )

    attention = []
    if data["unresolved_human_mentions"]:
        attention.append(f"{data['unresolved_human_mentions']} @human mentions unresolved")
    if data["silent_agents"]:
        attention.append(f"{', '.join(data['silent_agents'])} silent >{hours}h")

    if attention:
        lines.append("\n[ATTENTION NEEDED]")
        lines.extend(f"  - {item}" for item in attention)

    return "\n".join(lines)


def format_spawns(data: list[dict[str, Any]], limit: int) -> str:
    if not data:
        return "[SPAWNS] no completed spawns"

    lines = []
    insight_only_count = sum(1 for s in data if s["insight_only"])
    lines.append(f"[SPAWNS] last {len(data)} ({insight_only_count} insight-only)")

    for s in data:
        marker = "!" if s["insight_only"] else " "
        artifacts = s["artifacts"]
        transitions = s["task_transitions"]
        summary = truncate(s["summary"][:50]) if s["summary"] else "-"
        lines.append(
            f"{marker} {s['id']} @{s['agent']:10} {artifacts:2}a {transitions:2}t  {summary}"
        )

    return "\n".join(lines)


def format_swarm(data: dict[str, Any]) -> str:
    lines = []
    has_content = False

    if data["spawns"]:
        lines.append("[SPAWNS]")
        spawn_str = ", ".join(f"@{s['agent']}({s['count']})" for s in data["spawns"])
        lines.append(f"  {spawn_str}")
        has_content = True

    if data["active"]:
        lines.append("\n[ACTIVE]" if has_content else "[ACTIVE]")
        lines.extend(f"  @{t['agent']}: {t['content']}" for t in data["active"])
        has_content = True

    if data["committed"]:
        lines.append("\n[COMMITTED]" if has_content else "[COMMITTED]")
        lines.extend(f"  d/{d['id']}: {d['content']}" for d in data["committed"])
        has_content = True

    if data["questions"]:
        lines.append("\n[QUESTIONS]" if has_content else "[QUESTIONS]")
        lines.extend(f"  i/{q['id']} [{q['agent']}] {q['content']}" for q in data["questions"])
        has_content = True

    if data["insights"]:
        lines.append("\n[INSIGHTS]" if has_content else "[INSIGHTS]")
        for i in data["insights"]:
            tag = f"[{i['domain']}] " if i.get("domain") else ""
            lines.append(f"  i/{i['id']}: {tag}{i['content']}")
        has_content = True

    if data["recent"]:
        lines.append("\n[SUMMARIES]" if has_content else "[SUMMARIES]")
        lines.extend(f"  s/{r['id']}: @{r['agent']}: {r['summary']}" for r in data["recent"])

    return "\n".join(lines)
