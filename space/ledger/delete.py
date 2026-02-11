import argparse
import json
from typing import Any

from space import agents
from space.agents import identity as identity_lib
from space.core.errors import NotFoundError
from space.core.models import Decision, Insight, Reply, Task
from space.ledger import decisions, insights, replies, tasks
from space.lib import store
from space.lib.commands import echo, fail, space_cmd

ARTIFACTS: dict[str, tuple[str, type[Any], Any, Any]] = {
    "i": ("insights", Insight, insights.delete, insights.archive),
    "d": ("decisions", Decision, decisions.delete, decisions.archive),
    "t": ("tasks", Task, tasks.delete, None),
    "r": ("replies", Reply, replies.delete, None),
}
RESTORABLE = {"i"}


@space_cmd("delete")
def main() -> None:
    parser = argparse.ArgumentParser(description="soft delete entities by prefixed reference")
    parser.add_argument("entity_ref", help="i/xxx d/xxx t/xxx r/xxx")
    parser.add_argument("--restore", action="store_true", help="restore deleted entity (i/ only)")
    parser.add_argument("-j", "--json", action="store_true", help="output in JSON format")
    parser.add_argument("-a", "--as", dest="agent_ref", help="agent identity")
    args = parser.parse_args()

    agent_id = args.agent_ref or identity_lib.current()
    if not agent_id:
        fail("Missing: --as or SPACE_IDENTITY")
    agents.get_by_handle(agent_id)

    if len(args.entity_ref) < 3 or args.entity_ref[1] != "/":
        fail(f"Use prefix: {' '.join(f'{p}/' for p in ARTIFACTS)}")

    prefix = args.entity_ref[0]
    raw_id = args.entity_ref[2:]

    if prefix not in ARTIFACTS:
        fail(f"Unsupported prefix: {prefix}/")

    if args.restore and prefix not in RESTORABLE:
        fail(f"Restore not supported for {prefix}/")

    table, model, do_delete, do_archive = ARTIFACTS[prefix]
    try:
        entry = store.resolve(raw_id, table, model)
        if args.restore:
            result = do_archive(entry.id, restore=True)
            action = "Restored"
        else:
            if do_archive and prefix in {"i", "d"}:
                result = do_archive(entry.id)
                action = "Archived"
            else:
                do_delete(entry.id)
                result = entry
                action = "Deleted"
        if args.json:
            echo(json.dumps({"id": result.id, "deleted": action == "Deleted"}, indent=2))
        else:
            echo(f"{action} {store.ref(table, result.id)}")
    except NotFoundError:
        fail(f"Not found: {args.entity_ref}")
