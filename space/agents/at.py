import argparse
import json
import sys

from space import agents
from space.agents import spawn
from space.core.errors import NotFoundError, ValidationError
from space.core.types import SpawnId
from space.ledger import replies
from space.lib import paths, store
from space.lib.commands import echo, fail, space_cmd
from space.lib.providers import models


def _resolve_target(target: str) -> tuple[str, str]:
    if "/" in target:
        prefix = target.split("/", 1)[0]
        if prefix in {"s", "i", "d", "t", "r"}:
            return "ledger", target
    try:
        agent = agents.get_by_handle(target)
        return "handle", agent.handle
    except NotFoundError:
        pass

    raise ValidationError(f"Unknown target: {target}")


@space_cmd("@")
def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        parser = argparse.ArgumentParser(description="unified addressing")
        parser.add_argument("target", help="identity, spawn ref, or ledger ref")
        parser.add_argument("message", help="message or instruction")
        parser.add_argument("-m", "--model", help="model override")
        parser.add_argument("-s", "--skills", help="skills to inject (comma-separated)")
        parser.add_argument("-j", "--json", action="store_true", help="output as JSON")

        if len(sys.argv) > 1 and sys.argv[1] == "@":
            args = parser.parse_args(sys.argv[2:])
        else:
            args = parser.parse_args()

    kind, resolved = _resolve_target(args.target)
    model_id = models.resolve(args.model) if args.model else None
    skill_list = args.skills.split(",") if args.skills else None

    if kind == "handle":
        agent = agents.get_by_handle(resolved)
        s = spawn.launch(
            agent_id=agent.id,
            instruction=args.message,
            model_override=model_id,
            skills=skill_list,
        )
        if args.json:
            echo(json.dumps({"spawn_id": s.id, "identity": resolved}, indent=2))
            return
        echo(f"  s/{s.id[:8]} @{resolved}")

    elif kind == "ledger":
        ref_type, ref_id = store.resolve_short(args.target)

        if ref_type == "spawn":
            fail("ERROR: spawn inbox not implemented")

        human_agent = agents.get_human()
        if not human_agent:
            fail("ERROR: no human agent found")

        spawn_id_str = paths.spawn_id()
        spawn_id = SpawnId(spawn_id_str) if spawn_id_str else None
        reply = replies.create(
            parent_id=ref_id,
            author_id=human_agent.id,
            content=args.message,
            spawn_id=spawn_id,
        )
        if args.json:
            echo(json.dumps({"reply_id": reply.id, "parent": args.target}, indent=2))
            return
        echo(f"  {args.target}")
