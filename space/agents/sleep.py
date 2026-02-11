import json
from pathlib import Path

from space.agents import spawn
from space.core.models import Spawn, TaskStatus
from space.ledger import projects, tasks
from space.lib import git, paths, store
from space.lib.commands import echo, fail, space_cmd
from space.lib.display.format import truncate


@space_cmd("sleep")
def main(summary: str | None = None, json_output: bool = False, force: bool = False) -> None:
    spawn_id = paths.spawn_id()
    if not spawn_id:
        fail("Not in spawn context")

    s = store.resolve(spawn_id, "spawns", Spawn)
    project = projects.infer_from_cwd()
    has_uncommitted = _check_uncommitted(project.repo_path) if project else False

    if summary is None:
        _show_checklist(s, has_uncommitted, json_output)
        return

    if has_uncommitted and not force:
        fail("Uncommitted changes detected. Commit or use --force.")

    result = spawn.done(s, summary)
    if "error" in result:
        if json_output:
            echo(json.dumps(result, indent=2))
        else:
            echo(result["error"])
        fail("", code=1)

    if json_output:
        echo(json.dumps(result, indent=2))
    else:
        echo("Done.")


def _show_checklist(s: Spawn, has_uncommitted: bool, json_output: bool) -> None:
    all_tasks = tasks.fetch(assignee_id=s.agent_id)
    owned_tasks = [t for t in all_tasks if t.status == TaskStatus.ACTIVE]

    if json_output:
        echo(
            json.dumps(
                {
                    "spawn_id": s.id,
                    "tasks": [
                        {"id": t.id, "content": truncate(t.content, 100)} for t in owned_tasks
                    ],
                    "uncommitted": has_uncommitted,
                },
                indent=2,
            )
        )
        return

    if owned_tasks:
        echo("Open tasks:")
        for t in owned_tasks[:10]:
            echo(f"  - [{store.ref('tasks', t.id)}] {truncate(t.content)}")
        echo()
        echo("Before sleeping:")
        echo('  space task done <id> "result"    — complete work')
    else:
        echo("No tasks tracked this session.")
        echo()
        echo("Before sleeping:")
        echo('  space task add "what you did"    — log work (for provenance)')
    echo('  space decision "commitment"      — record decisions')
    echo('  space insight "pattern learned"  — capture patterns')
    if has_uncommitted:
        echo()
        echo("WARNING: Uncommitted changes detected. Commit or stash before sleeping.")
    echo()
    echo("Then:")
    echo('  space sleep "summary"')


def _check_uncommitted(cwd: str | None) -> bool:
    if not cwd:
        return False
    path = Path(cwd)
    if not path.exists():
        return False
    try:
        return git.dirty(path)
    except git.GitError:
        return False
