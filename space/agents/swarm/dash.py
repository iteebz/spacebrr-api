from collections.abc import Callable
from typing import Any

from space import stats
from space.agents import daemon
from space.lib.display import ansi
from space.lib.display import format as fmt

REF_COLOR: dict[str, Callable[[str], str]] = {
    "i": ansi.sage,
    "d": ansi.slate,
    "t": ansi.amber,
    "s": ansi.mauve,
}


def _group_by_project(live_data: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in live_data:
        if s["status"] == "active":
            key = s.get("project") or "forage"
        else:
            key = "sleeping"
        groups.setdefault(key, []).append(s)
    return groups


def _tag(name: str) -> str:
    return f"{ansi.DEFAULT.bold}{ansi.DEFAULT.white}<{name}>{ansi.DEFAULT.reset}"


def _section(
    items: list[dict[str, Any]],
    tag: str,
    prefix: str,
    content_key: str = "content",
    width: int = 60,
) -> list[str]:
    if not items:
        return []
    color = REF_COLOR.get(prefix, ansi.gray)
    lines = ["", _tag(tag)]
    lines.extend(
        f"  {color(f'{prefix}/{item["id"]}')} {ansi.gray(f'@{item.get("agent", ""):<11}')}"
        f"{ansi.white(fmt.truncate(item[content_key], width, flatten=True))}"
        for item in items
    )
    return lines


def render(frame: int | None = None) -> list[str]:
    data = stats.swarm()
    live_data = stats.live()
    daemon_status = daemon.status()
    return render_from(data, live_data, daemon_status, frame=frame)


def payload() -> dict[str, Any]:
    data = stats.swarm()
    live_data = stats.live()
    daemon_status = daemon.status()
    return {**data, "live": live_data, "daemon": daemon_status}


def render_from(
    data: dict[str, Any],
    live_data: list[dict[str, Any]],
    daemon_status: dict[str, Any],
    frame: int | None = None,
) -> list[str]:
    lines: list[str] = []

    active_count = sum(1 for s in live_data if s["status"] == "active")
    last_skip = daemon_status.get("last_skip")
    if active_count == 0 and daemon_status.get("enabled") and isinstance(last_skip, str):
        lines.extend([ansi.gray(f"sleeping ({fmt.ago(last_skip)})"), ""])

    groups = _group_by_project(live_data)

    brring = groups.pop("sleeping", [])
    project_keys = sorted(groups.keys(), key=lambda k: (k == "forage", k))

    if project_keys:
        lines.append(_tag("brring"))
        for group_idx, project_key in enumerate(project_keys):
            if group_idx > 0:
                lines.append("")
            lines.append(ansi.gray(f"  [{project_key}]"))
            for i, s in enumerate(groups[project_key]):
                lines.append(_agent_line(s, i, frame, active=True))

    if brring:
        lines.append("")
        lines.append(_tag("sleeping"))
        for i, s in enumerate(brring):
            lines.append(_agent_line(s, i, frame, active=False))

    lines.extend(_section(data["committed"], "decisions", "d", width=50))

    if data["insights"]:
        lines.append("")
        lines.append(_tag("insights"))
        lines.extend(
            f"  {ansi.sage(f'i/{ins["id"]}')} {ansi.gray(f'@{ins["agent"]:<11}')}"
            f"{ansi.gray(f'[{ins["domain"]}] ') if ins['domain'] else ''}"
            f"{ansi.white(fmt.truncate(ins['content'], 50, flatten=True))}"
            for ins in data["insights"]
        )

    lines.extend(_section(data["active"], "tasks", "t", width=50))
    lines.extend(_section(data["recent"], "sessions", "s", content_key="summary"))
    lines.extend(_section(data["questions"], "questions", "i"))

    return lines


def _agent_line(s: dict[str, Any], i: int, frame: int | None, *, active: bool) -> str:
    identity = s["handle"]
    color = ansi.agent_color(identity)
    pct_str = fmt.pct(s.get("health"), color=ansi.gray)
    artifact = fmt.truncate(s.get("artifact", ""), flatten=True)
    desc = s.get("description", "")
    last_active = s.get("last_active")

    if frame is not None and active:
        style = list(ansi.SPINNER_STYLES.keys())[hash(identity) % len(ansi.SPINNER_STYLES)]
        spin = ansi.spinner(frame + i, style)
        return (
            f"{pct_str} {color}{spin} {identity[:10]:<10}{ansi.DEFAULT.reset} "
            f"{ansi.white(artifact)}"
        )

    pfx = ">" if active else ansi.gray(f"{fmt.ago(last_active)}") if last_active else ansi.gray("·")
    label = desc if not active and desc else artifact
    label_color = ansi.gray if not active else ansi.white
    return f"{pct_str} {pfx} {color}{identity[:10]:<10}{ansi.DEFAULT.reset} {label_color(label)}"
