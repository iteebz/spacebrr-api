import argparse
import contextlib
import difflib
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any

from space import agents, ctx
from space.agents import spawn, swarm
from space.core.errors import NotFoundError, StateError
from space.core.models import Agent, Project, Spawn, SpawnMode, SpawnStatus
from space.core.types import AgentId
from space.ledger import decisions, insights, projects, tasks
from space.lib import hooks, store
from space.lib.commands import echo, fail, space_cmd
from space.lib.display import format as fmt
from space.lib.display.format import truncate
from space.lib.providers import models


def _spawn_table(
    spawn_list: list[Spawn],
    agent_map: dict[AgentId, Any],
    show_summary: bool = False,
) -> list[str]:
    lines = [
        f"{'ID':<10} {'Identity':<20} {'Mode':<10} {'Status':<12} {'Created':<8}",
        "-" * 64,
    ]
    for s in spawn_list:
        created = fmt.ago(s.created_at)
        agent = agent_map.get(s.agent_id)
        handle = agent.handle if agent else s.agent_id[:8]
        lines.append(
            f"{store.ref('spawns', s.id):<10} {handle:<20} {s.mode.value:<10} {s.status.value:<12} {created:<8}"
        )
        if show_summary and s.summary:
            lines.append(f"  {truncate(s.summary)}")
    return lines


def _resolve_agent_and_project(identity: str) -> tuple[Agent, Project]:
    agent = store.resolve(identity, "agents", Agent)
    if not agent.model:
        fail(f"Agent {identity} has no model configured")

    project = projects.infer_from_cwd()
    if not project:
        fail("No project found in current directory")

    return agent, project


def _resolve_project_cwd(project_ref: str | None) -> str | None:
    if not project_ref:
        return None
    project_id = projects.get_scope(project_ref)
    project = projects.get(project_id)
    if not project.repo_path:
        fail(f"Project {project.name} has no repo_path")
    return str(project.repo_path)


def _resolve_spawn_for_stop(ref: str) -> Spawn:
    with contextlib.suppress(NotFoundError):
        return store.resolve(ref, "spawns", Spawn)

    try:
        agent = store.resolve(ref, "agents", Agent)
    except NotFoundError:
        fail(f"Spawn not found: {ref}")

    active = spawn.fetch(agent_id=agent.id, status=["active"])
    if not active:
        fail(f"No active spawn for: {ref}")
    if len(active) > 1:
        fail(f"Multiple active spawns for {ref}, specify spawn ID")
    return active[0]


def _get_spawn_refs(s: Spawn) -> dict[str, list[dict[str, str]]]:
    refs: dict[str, list[dict[str, str]]] = {}

    task_list = tasks.fetch(spawn_ids=[s.id])
    if task_list:
        refs["tasks"] = [
            {
                "id": store.ref("tasks", t.id),
                "content": truncate(t.content),
                "status": t.status.value,
            }
            for t in task_list
        ]

    insight_list = insights.fetch(spawn_id=s.id, include_archived=True)
    if insight_list:
        refs["insights"] = [
            {"id": store.ref("insights", i.id), "content": truncate(i.content), "domain": i.domain}
            for i in insight_list
        ]

    decision_list = decisions.fetch(spawn_id=s.id)
    if decision_list:
        refs["decisions"] = [
            {"id": store.ref("decisions", d.id), "content": truncate(d.content)}
            for d in decision_list
        ]

    children = spawn.fetch(caller_ids=[s.id])
    if children:
        agent_ids = list({c.agent_id for c in children})
        agent_map = agents.batch_get(agent_ids)
        refs["children"] = [
            {
                "id": store.ref("spawns", c.id),
                "handle": agent_map.get(
                    c.agent_id, Agent(id=c.agent_id, handle=c.agent_id[:8])
                ).handle,
                "status": c.status.value,
            }
            for c in children
        ]

    return refs


def _usage_bar(pct: float, used: int, limit: int, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct}% ({used:,}/{limit:,})"


def _format_log_entry(e: spawn.LogEntry) -> list[str]:
    start_time = e.created_at[11:16] if e.created_at else "?"
    end_time = e.last_active_at[11:16] if e.last_active_at else "?"
    duration = fmt.format_duration(e.duration_seconds) if e.duration_seconds else "?"

    lines = [f"{e.id} {e.agent_handle} {start_time}->{end_time} ({duration}) {e.status}"]

    if e.summary:
        lines.append(f'  "{e.summary}"')

    if e.error:
        lines.append(f"  error: {truncate(e.error)}")

    if e.primitives:
        prim_strs = [f"{k}: {v['r']}r/{v['w']}w" for k, v in e.primitives.items()]
        lines.append(f"  {', '.join(prim_strs)}")

    return lines


@space_cmd("spawn")
def main() -> None:
    """Execution lifecycle."""
    parser = argparse.ArgumentParser(prog="spawn", description="Execution lifecycle")
    subs = parser.add_subparsers(dest="cmd")

    # spawn list
    list_p = subs.add_parser("list", aliases=["ls"], help="List spawns")
    list_p.add_argument("-a", "--active", action="store_true", help="Only active spawns")
    list_p.add_argument("-d", "--done", action="store_true", help="Only completed spawns")
    list_p.add_argument("-i", "--identity", help="Filter by agent")
    list_p.add_argument("-n", "--limit", type=int, default=20, help="Max spawns to show")
    list_p.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    # spawn show
    show_p = subs.add_parser("show", help="Show spawn details")
    show_p.add_argument("spawn_id", help="Spawn ID")
    show_p.add_argument("-r", "--refs", action="store_true", help="Show related entities")
    show_p.add_argument("-u", "--usage", action="store_true", help="Show context usage")
    show_p.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    # spawn history
    hist_p = subs.add_parser("history", help="Spawn session history")
    hist_p.add_argument("identity", nargs="?", help="Agent identity")
    hist_p.add_argument("-s", "--since", help="Time window (e.g. 8h, 1d)")
    hist_p.add_argument("-n", "--limit", type=int, default=10, help="Max entries")
    hist_p.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    # spawn trace
    trace_p = subs.add_parser("trace", help="Show spawn trace")
    trace_p.add_argument("spawn_id", help="Spawn ID")
    trace_p.add_argument("-n", "--limit", type=int, default=100, help="Max events")
    trace_p.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    # spawn resume
    resume_p = subs.add_parser("resume", help="Resume spawn")
    resume_p.add_argument("spawn_id", help="Spawn ID")
    resume_p.add_argument("prompt", nargs="?", default="continue", help="Prompt to send")

    # spawn stop
    stop_p = subs.add_parser("stop", help="Stop spawn")
    stop_p.add_argument("ref", help="Spawn ID or agent identity")

    # spawn wake
    wake_p = subs.add_parser("wake", help="Wake autonomous spawn")
    wake_p.add_argument("identity", help="Agent identity")
    wake_p.add_argument("-t", "--timeout", type=int, default=3600, help="Timeout in seconds")
    wake_p.add_argument("-s", "--skills", help="Skills to inject (comma-separated)")
    wake_p.add_argument("-p", "--project", help="Project scope (uses repo_path as cwd)")

    # spawn batch
    batch_p = subs.add_parser("batch", help="Launch batch of spawns")
    batch_p.add_argument("identities", nargs="+", help="Agent identities")
    batch_p.add_argument("-t", "--timeout", type=int, default=3600, help="Timeout in seconds")
    batch_p.add_argument(
        "-N", "--no-notify", action="store_true", help="Skip push on batch complete"
    )
    batch_p.add_argument("-p", "--project", help="Project scope (uses repo_path as cwd)")

    # spawn preview
    preview_p = subs.add_parser("preview", aliases=["ctx"], help="Preview spawn context")
    preview_p.add_argument("identity", help="Agent identity")
    preview_p.add_argument("-d", "--diff", dest="diff_with", help="Compare with another agent")

    # spawn run
    run_p = subs.add_parser("run", help="Directed spawn with instruction")
    run_p.add_argument("identity", help="Agent identity")
    run_p.add_argument("instruction", help="Task instruction")
    run_p.add_argument("-t", "--timeout", type=int, default=3600, help="Timeout in seconds")
    run_p.add_argument("-s", "--skills", help="Skills to inject (comma-separated)")
    run_p.add_argument("-p", "--project", help="Project scope (uses repo_path as cwd)")

    # spawn tail
    tail_p = subs.add_parser("tail", help="Live follow spawn execution")
    tail_p.add_argument("spawn_id", help="Spawn ID to tail")
    tail_p.add_argument("-v", "--verbose", action="store_true", help="Show edit diffs")

    # model shortcuts
    for model in ["haiku", "opus", "sonnet", "gpt", "flash"]:
        model_p = subs.add_parser(model, help=f"Directed spawn with {model}")
        model_p.add_argument("instruction", help="Task instruction")
        model_p.add_argument("-a", "--agent", help="Agent identity (default: current)")
        model_p.add_argument("-s", "--skills", help="Skills to inject (comma-separated)")
        model_p.add_argument("-t", "--timeout", type=int, default=3600, help="Timeout in seconds")
        model_p.add_argument("-p", "--project", help="Project scope (uses repo_path as cwd)")

    args = parser.parse_args(sys.argv[2:])

    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    if args.cmd in ("list", "ls"):
        _list_spawns(args.active, args.done, args.identity, args.limit, args.json)
    elif args.cmd == "show":
        _show(args.spawn_id, args.refs, args.usage, args.json)
    elif args.cmd == "history":
        _history(args.identity, args.since, args.limit, args.json)
    elif args.cmd == "trace":
        _trace(args.spawn_id, args.limit, args.json)
    elif args.cmd == "resume":
        _resume(args.spawn_id, args.prompt)
    elif args.cmd == "stop":
        _stop(args.ref)
    elif args.cmd == "wake":
        _wake(args.identity, args.timeout, args.skills, args.project)
    elif args.cmd == "batch":
        _batch(args.identities, args.timeout, not args.no_notify, args.project)
    elif args.cmd in ("preview", "ctx"):
        _preview(args.identity, args.diff_with)
    elif args.cmd == "run":
        _run(args.identity, args.instruction, args.timeout, args.skills, args.project)
    elif args.cmd == "tail":
        _tail(args.spawn_id, args.verbose)
    elif args.cmd in ("haiku", "opus", "sonnet", "gpt", "flash"):
        _model_spawn(
            args.cmd, args.instruction, args.agent, args.skills, args.timeout, args.project
        )


def _list_spawns(
    active: bool, done: bool, identity: str | None, limit: int, json_output: bool
) -> None:
    if active and done:
        fail("Cannot use both --active and --done")
    status_filter = ["active"] if active else (["done"] if done else None)
    agent = store.resolve(identity, "agents", Agent) if identity else None

    spawns_list = spawn.fetch(
        agent_id=agent.id if agent else None,
        status=status_filter,
        limit=limit,
    )

    if json_output:
        echo(
            json.dumps(
                [
                    {
                        "id": s.id,
                        "agent_id": s.agent_id,
                        "mode": s.mode.value,
                        "status": s.status.value,
                    }
                    for s in spawns_list
                ],
                indent=2,
            )
        )
        return

    if not spawns_list:
        echo("No spawn.")
        return

    agent_ids = list({s.agent_id for s in spawns_list})
    agent_map = agents.batch_get(agent_ids)
    for line in _spawn_table(spawns_list, agent_map):
        echo(line)


def _show(spawn_id: str, refs: bool, usage: bool, json_output: bool) -> None:
    s = store.resolve(spawn_id, "spawns", Spawn)
    agent = agents.get(s.agent_id)
    trace_path = spawn.events_file_path(s.id)
    resumed = spawn.was_resumed(s.id)

    if json_output:
        data: dict[str, Any] = {
            "id": s.id,
            "handle": agent.handle,
            "mode": s.mode.value,
            "status": s.status.value,
            "resumed": resumed,
            "summary": s.summary,
            "created_at": s.created_at,
            "trace": str(trace_path) if trace_path else None,
        }
        if refs:
            data["refs"] = _get_spawn_refs(s)
        if usage:
            data["usage"] = spawn.usage(s)
        echo(json.dumps(data, indent=2))
        return

    echo(f"{store.ref('spawns', s.id)} ({agent.handle})")
    echo(f"Mode: {s.mode.value}")
    echo(f"Status: {s.status.value}")
    if resumed is not None:
        echo(f"Resumed: {resumed}")
    if s.summary:
        echo(f"Summary: {s.summary}")
    if trace_path:
        echo(f"Trace: {trace_path}")

    if usage:
        usage_data = spawn.usage(s)
        if usage_data:
            echo(
                f"Context: {_usage_bar(usage_data['percentage'], usage_data['context_used'], usage_data['context_limit'])}"
            )

    if refs:
        spawn_refs = _get_spawn_refs(s)
        if spawn_refs:
            echo("")
            echo("References:")
            for ref_type, items in spawn_refs.items():
                echo(f"  {ref_type}:")
                for item in items:
                    if ref_type == "children":
                        echo(f"    [{item['id']}] {item['handle']} ({item['status']})")
                    else:
                        echo(f"    [{item['id']}] {item['content']}")


def _history(identity: str | None, since: str | None, limit: int, json_output: bool) -> None:
    since_iso: str | None = None
    if since:
        try:
            delta = fmt.parse_duration(since)
        except ValueError:
            fail(f"Invalid duration: {since}")
        since_iso = (datetime.now(UTC) - delta).isoformat()

    agent_id = None
    if identity:
        agent = store.resolve(identity, "agents", Agent)
        agent_id = agent.id

    entries = spawn.log(
        agent_id=agent_id,
        since=since_iso,
        limit=limit,
    )

    if json_output:
        echo(
            json.dumps(
                [
                    {
                        "id": e.id,
                        "agent": e.agent_handle,
                        "status": e.status,
                        "created_at": e.created_at,
                        "last_active_at": e.last_active_at,
                        "duration_seconds": e.duration_seconds,
                        "summary": e.summary,
                        "error": e.error,
                        "primitives": e.primitives,
                    }
                    for e in entries
                ],
                indent=2,
            )
        )
        return

    if not entries:
        msg = "No spawns"
        if since:
            msg += f" in last {since}"
        echo(f"{msg}.")
        return

    for e in entries:
        for line in _format_log_entry(e):
            echo(line)
        echo("")


def _trace(spawn_id: str, limit: int, json_output: bool) -> None:
    s = store.resolve(spawn_id, "spawns", Spawn)
    page = spawn.read_events(s.id, limit=limit)

    if json_output:
        echo(json.dumps(page.events, indent=2))
        return

    if not page.events:
        echo("No trace events.")
        return

    for event in page.events:
        line = spawn.format_event(event)
        if line:
            echo(line)

    if page.has_more:
        echo(f"... +{page.total - limit} more events")


def _resume(spawn_id: str, prompt: str) -> None:
    s = store.resolve(spawn_id, "spawns", Spawn)
    agent = agents.get(s.agent_id)

    echo(f"Resuming {store.ref('spawns', spawn_id)} ({agent.handle})...")
    try:
        spawn.launch(agent_id=agent.id, spawn=s, instruction=prompt)
    except StateError as e:
        fail(str(e))
    echo(f"Resumed: {store.ref('spawns', spawn_id)}")


def _stop(ref: str) -> None:
    s = _resolve_spawn_for_stop(ref)

    if s.status != SpawnStatus.ACTIVE:
        echo(f"Spawn already {s.status}")
        return

    spawn.terminate(s.id)
    echo(f"Stopped: {store.ref('spawns', s.id)}")


def _wake(identity: str, timeout: int, skills: str | None, project_ref: str | None) -> None:
    agent, project = _resolve_agent_and_project(identity)
    skill_list = skills.split(",") if skills else None
    cwd = _resolve_project_cwd(project_ref) or (project.repo_path if project else None)
    s = spawn.launch(
        agent_id=agent.id,
        timeout_seconds=timeout,
        mode=SpawnMode.SOVEREIGN,
        skills=skill_list,
        cwd=cwd,
    )
    echo(f"Spawned: {store.ref('spawns', s.id)} ({agent.handle})")


def _batch(identities: list[str], timeout: int, notify: bool, project_ref: str | None) -> None:
    cwd = _resolve_project_cwd(project_ref)
    if not cwd:
        project = projects.infer_from_cwd()
        cwd = project.repo_path if project else None

    spawn_ids: list[str] = []
    for identity in identities:
        agent = store.resolve(identity, "agents", Agent)
        if not agent.model:
            echo(f"Agent {identity} has no model configured", err=True)
            continue
        s = spawn.launch(
            agent_id=agent.id,
            timeout_seconds=timeout,
            mode=SpawnMode.SOVEREIGN,
            cwd=cwd,
        )
        spawn_ids.append(s.id)
        echo(f"Spawned: {store.ref('spawns', s.id)} ({agent.handle})")

    if spawn_ids and notify:
        batch_id = hooks.create_batch(spawn_ids, notify=True)
        echo(f"Batch: {batch_id} ({len(spawn_ids)} spawns)")


def _preview(identity: str, diff_with: str | None) -> None:
    preview1 = ctx.wake(identity=identity)
    if diff_with:
        preview2 = ctx.wake(identity=diff_with)
        diff = difflib.unified_diff(
            preview1.splitlines(keepends=True),
            preview2.splitlines(keepends=True),
            fromfile=identity,
            tofile=diff_with,
        )
        echo("".join(diff))
        return
    echo(preview1)


def _run(
    identity: str, instruction: str, timeout: int, skills: str | None, project_ref: str | None
) -> None:
    agent, project = _resolve_agent_and_project(identity)
    skill_list = skills.split(",") if skills else None
    cwd = _resolve_project_cwd(project_ref) or (project.repo_path if project else None)
    s = spawn.launch(
        agent_id=agent.id,
        skills=skill_list,
        instruction=instruction,
        timeout_seconds=timeout,
        mode=SpawnMode.DIRECTED,
        cwd=cwd,
    )
    echo(f"Directed spawn: {store.ref('spawns', s.id)} ({agent.handle})")


def _tail(spawn_id: str, verbose: bool) -> None:
    s = store.resolve(spawn_id, "spawns", Spawn)
    agent = agents.get(s.agent_id)
    handle = agent.handle if agent else s.agent_id[:8]

    agent_cache: dict[str, str] = {}
    path = swarm.spawn_path(s, agent_cache)
    if not path or not path.exists():
        fail(f"No trace file found for spawn {spawn_id}")

    stream = swarm.StreamState(
        spawn_id=s.id,
        handle=handle,
        path=path,
        position=0,
        model=agent.model if agent else None,
    )

    try:
        while True:
            events = swarm.read_stream(stream, verbose=verbose)
            for _, line in events:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()

            if s.status == SpawnStatus.DONE:
                swarm.read_stream(stream, verbose=verbose, flush=True)
                break

            time.sleep(0.1)
    except KeyboardInterrupt:
        pass


def _model_spawn(
    model_alias: str,
    instruction: str,
    identity_arg: str | None,
    skills: str | None,
    timeout: int,
    project_ref: str | None,
) -> None:
    identity = identity_arg or "zealot"

    agent = store.resolve(identity, "agents", Agent)
    model_id = models.resolve(model_alias)
    if not model_id:
        fail(f"Unknown model: {model_alias}")

    skill_list = skills.split(",") if skills else None
    cwd = _resolve_project_cwd(project_ref)
    if not cwd:
        project = projects.infer_from_cwd()
        cwd = project.repo_path if project else None

    s = spawn.launch(
        agent_id=agent.id,
        instruction=instruction,
        model_override=model_id,
        skills=skill_list,
        timeout_seconds=timeout,
        mode=SpawnMode.DIRECTED,
        cwd=cwd,
    )

    echo(f"s/{s.id[:8]} @{agent.handle} ({model_alias})")
    _tail(s.id, verbose=False)
