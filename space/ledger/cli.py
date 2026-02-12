import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from space import agents
from space.agents import identity as identity_lib
from space.core.errors import NotFoundError, StateError, ValidationError
from space.core.models import Agent, Decision, Project, Task, TaskStatus
from space.core.types import ArtifactType, DecisionId, SpawnId
from space.ledger import (
    decisions,
    inbox,
    insights,
    ledger,
    projects,
    replies,
    search,
    tasks,
)
from space.ledger import (
    status as status_mod,
)
from space.lib import paths, store
from space.lib.commands import fail
from space.lib.display import ansi
from space.lib.display.format import ago


def _resolve_agent(ref: str | None) -> Agent:
    agent_id = ref or identity_lib.current()
    if not agent_id:
        fail("Missing: --as or SPACE_IDENTITY")
    return agents.get_by_handle(agent_id)


def route(args: argparse.Namespace) -> None:
    if args.action == "add":
        _add(args)
    elif args.action == "list":
        _list(args)
    elif args.action == "show":
        _show(args)
    elif args.action == "inbox":
        _inbox(args)
    elif args.action == "commit":
        _commit(args)
    elif args.action == "reject":
        _reject(args)
    elif args.action == "action":
        _action(args)
    elif args.action == "search":
        _search(args)
    elif args.action == "close":
        _close(args)
    elif args.action == "cancel":
        _cancel(args)


def _add(args: argparse.Namespace) -> None:
    if not args.artifact:
        fail("type and content required for add")

    type_arg = args.artifact[0]
    content_args = args.artifact[1:]

    if not content_args and type_arg != "p":
        fail(f"content required for add {type_arg}")

    content = " ".join(content_args)
    agent = _resolve_agent(None)
    project_id = projects.get_scope()
    spawn_id = SpawnId(sid) if (sid := paths.spawn_id()) else None

    if type_arg == "i":
        if not args.domain:
            fail("--domain required for insight add")
        try:
            entry = insights.create(
                project_id,
                agent.id,
                content,
                args.domain,
                spawn_id=spawn_id,
            )
            sys.stdout.write(f"{store.ref('insights', entry.id)}\n")
        except ValidationError as e:
            fail(str(e))
    elif type_arg == "t":
        entry = tasks.create(project_id, agent.id, content, spawn_id=spawn_id)
        sys.stdout.write(f"{store.ref('tasks', entry.id)}\n")
    elif type_arg == "d":
        if not args.why:
            fail("--why <rationale> required for decision add")
        try:
            entry = decisions.create(
                project_id,
                agent.id,
                content,
                args.why,
                spawn_id=spawn_id,
                refs=args.refs,
            )
            sys.stdout.write(f"{store.ref('decisions', entry.id)}\n")
        except ValidationError as e:
            fail(str(e))
    elif type_arg == "r":
        if len(content_args) < 2:
            fail("Usage: ledger add r <ref> <message>")
        ref = content_args[0]
        message = " ".join(content_args[1:])
        try:
            reply_entry = replies.create_by_ref(ref, agent.id, message, spawn_id=spawn_id)
            sys.stdout.write(f"{store.ref('replies', reply_entry.id)}\n")
        except (ValidationError, NotFoundError) as e:
            fail(str(e))
    elif type_arg == "p":
        try:
            project_entry = projects.create(content_args[0])
            sys.stdout.write(f"Project: {project_entry.name} ({project_entry.id[:8]})\n")
        except Exception as e:
            fail(str(e))
    else:
        fail(f"Unknown type for add: {type_arg}")


def _list(args: argparse.Namespace) -> None:
    project_id = projects.get_scope()
    type_arg = args.artifact[0] if args.artifact else "t"

    if type_arg == "all":
        items = ledger.fetch(limit=50, project_id=project_id)
        for item in items:
            sys.stdout.write(f"[{item.created_at}] {item.handle}: {item.content}\n")

    elif type_arg == "i":
        entries = insights.fetch(project_id=project_id, limit=50)
        for e in entries:
            try:
                agent = agents.get(e.agent_id)
                handle = agent.handle
            except NotFoundError:
                handle = "unknown"
            sys.stdout.write(f"[{store.ref('insights', e.id)}] @{handle}: {e.content}\n")
    elif type_arg == "t":
        task_list = tasks.fetch(project_id=project_id, limit=50)
        for t in task_list:
            mark = "✓" if t.status == TaskStatus.DONE else " "
            ref = store.ref("tasks", t.id)
            sys.stdout.write(f"{mark} {ref} {t.content}\n")
    elif type_arg == "d":
        decision_list = decisions.fetch(project_id=project_id, limit=50)
        for d in decision_list:
            if d.rejected_at:
                mark = "✗"
            elif d.actioned_at:
                mark = "✓"
            elif d.committed_at:
                mark = "◆"
            else:
                mark = "◇"
            ref = store.ref("decisions", d.id)
            sys.stdout.write(f"{mark} {ref} {d.content}\n")
    elif type_arg == "p":
        project_list = projects.fetch()
        if not project_list:
            sys.stdout.write("No projects found.\n")
            return

        project_ids = [p.id for p in project_list]
        last_active_map = projects.batch_last_active(project_ids)
        artifact_count_map = projects.batch_artifact_counts(project_ids)

        projects_sorted = sorted(
            project_list,
            key=lambda p: last_active_map.get(p.id) or "",
            reverse=True,
        )

        home = str(Path.home())
        rows = []
        for p in projects_sorted:
            count = artifact_count_map.get(p.id, 0)
            last = last_active_map.get(p.id)
            path = p.repo_path or "-"
            if path != "-" and path.startswith(home):
                path = "~" + path[len(home) :]
            tags = ",".join(p.tags) if p.tags else ""
            rows.append((p.name, str(count), ago(last), path, tags))

        name_w = max(len(r[0]) for r in rows)
        art_w = max(len(r[1]) for r in rows)
        act_w = max(len(r[2]) for r in rows)
        path_w = max(len(r[3]) for r in rows)

        sys.stdout.write(
            f"{'name':<{name_w}} {'artifacts':<{art_w}} {'active':<{act_w}} {'path':<{path_w}} {'tags'}\n"
        )
        sys.stdout.write("-" * (name_w + art_w + act_w + path_w + 20) + "\n")

        for name, count, last, path, tags in rows:
            sys.stdout.write(
                f"{name:<{name_w}} {count:<{art_w}} {last:<{act_w}} {path:<{path_w}} {tags}\n"
            )
    else:
        fail(f"Unknown type for list: {type_arg}")


def _show(args: argparse.Namespace) -> None:
    if not args.artifact:
        fail("ref required for show")

    ref = args.artifact[0]

    # Handle project show by name (no prefix)
    if "/" not in ref:
        try:
            project = store.resolve(ref, "projects", Project)
            sys.stdout.write(f"Project: {project.name}\n")
            sys.stdout.write(f"ID: {project.id}\n")
            sys.stdout.write(f"Repo: {project.repo_path}\n")
            return
        except NotFoundError:
            pass

    # Use ledger.thread for unified show
    try:
        if "/" in ref:
            prefix, short_id = ref.split("/", 1)
            table_map = {"i": "insight", "d": "decision", "t": "task"}
            item_type = table_map.get(prefix)
            if not item_type:
                fail(f"Invalid prefix: {prefix}")
        else:
            fail("Ref must be prefixed (i/xxx, d/xxx, t/xxx) or a project name")

        main_item, thread_items = ledger.thread(item_type, short_id)
        if not main_item:
            fail(f"Not found: {ref}")

        if args.json:
            _show_json(main_item, thread_items, ref, item_type)
        else:
            _show_formatted(main_item, thread_items, ref, item_type)

        # Mark as read (clears from inbox)
        agent = _resolve_agent(None)
        spawn_id = SpawnId(sid) if (sid := paths.spawn_id()) else None
        full_id = main_item.id
        artifact_type: ArtifactType = item_type  # type: ignore[assignment]
        inbox.mark_read(artifact_type, full_id, agent.id, spawn_id)

    except Exception as e:
        fail(f"Error: {e}")


def _show_json(main_item, thread_items, ref: str, item_type: str) -> None:
    data = {
        "ref": ref,
        "id": main_item.id,
        "type": item_type,
        "handle": main_item.handle,
        "content": main_item.content,
        "created_at": main_item.created_at,
    }
    if main_item.rationale:
        data["rationale"] = main_item.rationale
    if main_item.status:
        data["status"] = main_item.status

    if item_type == "decision":
        try:
            decision = decisions.get(DecisionId(main_item.id))
            if decision.committed_at:
                data["committed_at"] = decision.committed_at
            if decision.actioned_at:
                data["actioned_at"] = decision.actioned_at
            if decision.rejected_at:
                data["rejected_at"] = decision.rejected_at
            if hasattr(decision, "outcome") and decision.outcome:
                data["outcome"] = decision.outcome
        except NotFoundError:
            pass

    if thread_items:
        data["thread"] = [
            {
                "type": item.type,
                "id": item.id,
                "handle": item.handle,
                "content": item.content,
                "created_at": item.created_at,
            }
            for item in thread_items
        ]
    sys.stdout.write(json.dumps(data, indent=2))
    sys.stdout.write("\n")


def _show_formatted(main_item, thread_items, ref: str, item_type: str) -> None:
    tty = sys.stdout.isatty()

    if item_type == "decision":
        try:
            decision = decisions.get(DecisionId(main_item.id))
            _render_decision_card(decision, ref, tty)
        except NotFoundError:
            _render_generic(main_item, ref, tty)
    else:
        _render_generic(main_item, ref, tty)

    if thread_items:
        if tty:
            sys.stdout.write(f"\n{ansi.dim('─' * 40)}\n")
            sys.stdout.write(f"{ansi.gray(f'{len(thread_items)} related')}\n\n")
        else:
            sys.stdout.write(f"\n--- {len(thread_items)} related ---\n")

        for item in thread_items:
            item_ref = f"{item.type[0]}/{item.id[:8]}"
            if tty:
                sys.stdout.write(f"  {ansi.cyan(item_ref)} ")
                sys.stdout.write(f"{ansi.dim('@')}{ansi.gray(item.handle)}: ")
                sys.stdout.write(f"{ansi.dim(item.content[:80])}\n")
            else:
                sys.stdout.write(f"  {item_ref} @{item.handle}: {item.content[:80]}\n")


def _render_generic(item, ref: str, tty: bool) -> None:
    if tty:
        sys.stdout.write(f"{ansi.bold('[')}{ansi.cyan(ref)}{ansi.bold(']')} ")
        sys.stdout.write(f"{ansi.dim('@')}{ansi.gray(item.handle)}: ")
        sys.stdout.write(f"{ansi.white(item.content)}\n")
    else:
        sys.stdout.write(f"[{ref}] @{item.handle}: {item.content}\n")

    if item.rationale:
        label = ansi.dim("Rationale:") if tty else "Rationale:"
        sys.stdout.write(f"{label} {item.rationale}\n")
    if item.status:
        label = ansi.dim("Status:") if tty else "Status:"
        status = ansi.bold(item.status) if tty else item.status
        sys.stdout.write(f"{label} {status}\n")


def _render_decision_card(decision: Decision, ref: str, tty: bool) -> None:
    color: Callable[[str], str]
    if decision.rejected_at:
        mark = "✗ REJECTED"
        color = ansi.red if tty else (lambda x: x)
    elif decision.actioned_at:
        mark = "✓ ACTIONED"
        color = ansi.green if tty else (lambda x: x)
    elif decision.committed_at:
        mark = "◆ COMMITTED"
        color = ansi.yellow if tty else (lambda x: x)
    else:
        mark = "◇ PROPOSED"
        color = ansi.gray if tty else (lambda x: x)

    if tty:
        sys.stdout.write(f"{ansi.bold(color(mark))} {ansi.cyan(ref)}\n")
        sys.stdout.write(f"{ansi.dim('─' * 40)}\n")
    else:
        sys.stdout.write(f"{mark} {ref}\n")
        sys.stdout.write("─" * 40 + "\n")

    sys.stdout.write(f"{decision.content}\n\n")

    agent = agents.get(decision.agent_id)
    if tty:
        sys.stdout.write(f"{ansi.dim('Author:')} {ansi.gray(f'@{agent.handle}')}\n")
        sys.stdout.write(f"{ansi.dim('Created:')} {ansi.gray(ago(decision.created_at))}\n")
    else:
        sys.stdout.write(f"Author: @{agent.handle}\n")
        sys.stdout.write(f"Created: {ago(decision.created_at)}\n")

    if decision.committed_at:
        label = ansi.dim("Committed:") if tty else "Committed:"
        value = ansi.gray(ago(decision.committed_at)) if tty else ago(decision.committed_at)
        sys.stdout.write(f"{label} {value}\n")
    if decision.actioned_at:
        label = ansi.dim("Actioned:") if tty else "Actioned:"
        value = ansi.gray(ago(decision.actioned_at)) if tty else ago(decision.actioned_at)
        sys.stdout.write(f"{label} {value}\n")
    if decision.rejected_at:
        label = ansi.dim("Rejected:") if tty else "Rejected:"
        value = ansi.gray(ago(decision.rejected_at)) if tty else ago(decision.rejected_at)
        sys.stdout.write(f"{label} {value}\n")

    if decision.rationale:
        sys.stdout.write("\n")
        if tty:
            sys.stdout.write(f"{ansi.dim('Rationale:')}\n{ansi.gray(decision.rationale)}\n")
        else:
            sys.stdout.write(f"Rationale:\n{decision.rationale}\n")

    if hasattr(decision, "outcome") and decision.outcome:
        sys.stdout.write("\n")
        if tty:
            sys.stdout.write(f"{ansi.dim('Outcome:')}\n{ansi.gray(decision.outcome)}\n")
        else:
            sys.stdout.write(f"Outcome:\n{decision.outcome}\n")


def _inbox(args: argparse.Namespace) -> None:
    agent = _resolve_agent(None)
    current_handle = agent.handle

    project_id = projects.get_scope(args.project) if hasattr(args, "project") else None
    items = inbox.fetch(current_handle, project_id=project_id)
    if not items:
        sys.stdout.write("Inbox empty\n")
        return

    if args.json:
        sys.stdout.write(json.dumps([asdict(i) for i in items], indent=2))
        sys.stdout.write("\n")
        return

    for item in items:
        sys.stdout.write(f"[{item.type[0]}/{item.id[:8]}] {item.reason}: {item.content[:100]}\n")


def _commit(args: argparse.Namespace) -> None:
    if not args.artifact:
        fail("decision ref required for commit")
    decision_ref = args.artifact[0]
    try:
        decision = store.resolve(decision_ref, "decisions", Decision)
        updated = decisions.commit(decision.id)
        if args.json:
            sys.stdout.write(json.dumps(asdict(updated), indent=2))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(f"Committed: {store.ref('decisions', decision.id)}\n")
    except (NotFoundError, ValidationError) as e:
        fail(str(e))


def _reject(args: argparse.Namespace) -> None:
    if not args.artifact:
        fail("decision ref required for reject")
    decision_ref = args.artifact[0]
    try:
        decision = store.resolve(decision_ref, "decisions", Decision)
        updated = decisions.reject(decision.id)
        if args.json:
            sys.stdout.write(json.dumps(asdict(updated), indent=2))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(f"Rejected: {store.ref('decisions', decision.id)}\n")
    except (NotFoundError, ValidationError) as e:
        fail(str(e))


def _action(args: argparse.Namespace) -> None:
    if not args.artifact:
        fail("decision ref required for action")
    decision_ref = args.artifact[0]
    try:
        decision = store.resolve(decision_ref, "decisions", Decision)
        updated = decisions.action(decision.id, outcome=args.outcome)
        if args.json:
            sys.stdout.write(json.dumps(asdict(updated), indent=2))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(f"Actioned: {store.ref('decisions', decision.id)}\n")
            if args.outcome:
                sys.stdout.write(f"Outcome: {args.outcome}\n")
    except (NotFoundError, ValidationError) as e:
        fail(str(e))


def _search(args: argparse.Namespace) -> None:
    if not args.artifact:
        fail("query required for search")

    query_str = " ".join(args.artifact)
    project_id = projects.get_scope() if not args.all_projects else None

    results = search.query(
        query_str,
        scope="all",
        limit=args.limit if hasattr(args, "limit") else 20,
        project_id=project_id,
    )

    if args.json:
        data = [
            {
                "source": r.source,
                "content": r.content,
                "reference": r.reference,
                "timestamp": r.timestamp,
                "weight": r.weight,
                "metadata": r.metadata,
            }
            for r in results
        ]
        sys.stdout.write(json.dumps({"query": query_str, "results": data}, indent=2))
        sys.stdout.write("\n")
    else:
        if not results:
            sys.stdout.write(f"No results for '{query_str}'\n")
            return

        sys.stdout.write(f"Found {len(results)} results:\n\n")
        for result in results:
            content = result.content.replace("\n", " ").strip()
            if len(content) > 200:
                content = content[:197] + "..."
            sys.stdout.write(f"[{result.source}] {result.reference}\n")
            sys.stdout.write(f"  {content}\n\n")


def _close(args: argparse.Namespace) -> None:
    if not args.artifact:
        fail("task ref required for close")
    task_ref = args.artifact[0]
    try:
        task = store.resolve(task_ref, "tasks", Task)
        agent = _resolve_agent(None)
        tasks.set_status(task.id, TaskStatus.DONE, agent_id=agent.id)
        sys.stdout.write(f"Closed: {store.ref('tasks', task.id)}\n")
    except (NotFoundError, ValidationError, StateError) as e:
        fail(str(e))


def _cancel(args: argparse.Namespace) -> None:
    if not args.artifact:
        fail("task ref required for cancel")
    task_ref = args.artifact[0]
    try:
        task = store.resolve(task_ref, "tasks", Task)
        agent = _resolve_agent(None)
        tasks.set_status(task.id, TaskStatus.CANCELLED, agent_id=agent.id)
        sys.stdout.write(f"Cancelled: {store.ref('tasks', task.id)}\n")
    except (NotFoundError, ValidationError, StateError) as e:
        fail(str(e))


def status_cmd(agent_handle: str | None = None, json_output: bool = False) -> None:
    data = status_mod.get(agent_handle)

    if json_output:
        payload = {
            "projects": [
                {
                    "name": p.name,
                    "open_questions": p.open_questions,
                    "unclaimed_tasks": p.unclaimed_tasks,
                    "committed_decisions": p.committed_decisions,
                }
                for p in data.projects
            ],
            "inbox": [{"id": i.id, "content": i.content} for i in data.inbox],
        }
        sys.stdout.write(json.dumps(payload, indent=2))
        sys.stdout.write("\n")
        return

    for project in data.projects:
        needs: list[str] = []
        if project.open_questions:
            needs.append(f"{project.open_questions} questions")
        if project.unclaimed_tasks:
            needs.append(f"{project.unclaimed_tasks} tasks")
        if project.committed_decisions:
            needs.append(f"{project.committed_decisions} decisions")

        if needs:
            sys.stdout.write(f"**{project.name}**: {', '.join(needs)}\n")
        else:
            sys.stdout.write(f"**{project.name}**: clear\n")

    if data.inbox:
        sys.stdout.write("\n## Inbox\n")
        for item in data.inbox:
            sys.stdout.write(f"  [{item.parent_type[0]}/{item.parent_id}] {item.content[:60]}...\n")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ledger", description="unified ledger access")
    parser.add_argument(
        "action",
        choices=[
            "add",
            "list",
            "show",
            "inbox",
            "commit",
            "reject",
            "action",
            "search",
            "close",
            "cancel",
        ],
        help="ledger action",
    )
    parser.add_argument("artifact", nargs="*", help="artifact type/ref/content")
    parser.add_argument("-d", "--domain", help="domain for insight add")
    parser.add_argument("-w", "--why", help="rationale for decision add")
    parser.add_argument("-r", "--refs", help="references for decision add")
    parser.add_argument("-o", "--outcome", help="outcome for decision action")
    parser.add_argument("-n", "--limit", type=int, default=20, help="search result limit")
    parser.add_argument("-g", "--all-projects", action="store_true", help="search all projects")
    parser.add_argument("--project", help="filter to project scope")
    parser.add_argument("-j", "--json", action="store_true", help="output as JSON")
    args = parser.parse_args()
    route(args)
