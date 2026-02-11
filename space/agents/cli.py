import argparse
import json
import sys
from typing import Any

from space import agents, ctx
from space.agents import defaults
from space.agents import identity as identity_lib
from space.core.errors import ConflictError, NotFoundError
from space.core.models import Agent
from space.core.types import UNSET, Unset
from space.core.types import AgentType as AgentTypeT
from space.lib import providers, store
from space.lib.commands import echo, fail, space_cmd
from space.lib.display.format import ago


@space_cmd("identity")
def identity_main() -> None:
    """Manage your human identity."""
    parser = argparse.ArgumentParser(prog="identity", description="Manage your human identity.")
    subs = parser.add_subparsers(dest="cmd")

    set_p = subs.add_parser("set", help="Set your human identity")
    set_p.add_argument("name", help="Your identity name")

    subs.add_parser("get", help="Show your current identity")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    if args.cmd == "set":
        _identity_set(args.name)
    elif args.cmd == "get":
        _identity_get()


def _identity_set(name: str) -> None:
    if " " in name:
        fail("Identity cannot contain spaces. Use hyphens instead.")

    try:
        existing = store.resolve(name, "agents", Agent)
        if existing.model:
            fail(f"Identity '{name}' already registered as agent. Choose different name.")
    except (NotFoundError, ValueError):
        pass

    try:
        human_agent = store.resolve("human", "agents", Agent)
    except (NotFoundError, ValueError):
        fail(
            "No human identity found. Register yourself: agents register <name> [--model <model>]."
        )

    if name == "human":
        echo("Already set to: human")
        return

    try:
        agents.repo.rename(human_agent.id, name)
        echo(f"Identity set to: {name}")
    except ConflictError as e:
        fail(f"Failed to set identity: {e}")


def _identity_get() -> None:
    humans = agents.repo.fetch(type="human")
    if humans:
        echo(humans[0].handle)
    else:
        fail(
            "No human identity found. Register yourself: agents register <name> [--model <model>]."
        )


@space_cmd("agent")
def agent_main() -> None:
    """Identity registry."""
    parser = argparse.ArgumentParser(prog="agent", description="Identity registry")
    subs = parser.add_subparsers(dest="cmd")

    # agent list
    list_p = subs.add_parser("list", aliases=["ls"], help="List available agents")
    list_p.add_argument("-a", "--archived", action="store_true", help="Include archived")
    list_p.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    # agent humans
    humans_p = subs.add_parser("humans", help="List human agents")
    humans_p.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    # agent info
    info_p = subs.add_parser("info", help="Show agent details")
    info_p.add_argument("handle", help="Agent handle")
    info_p.add_argument("-j", "--json", action="store_true", help="Output as JSON")
    info_p.add_argument("-i", "--identity", action="store_true", help="Show identity text")

    # agent create
    create_p = subs.add_parser("create", help="Register agent")
    create_p.add_argument("handle", help="Agent handle")
    create_p.add_argument("-m", "--model", help="Model ID")
    create_p.add_argument("-i", "--identity", help="Identity filename")

    # agent update
    update_p = subs.add_parser("update", help="Modify agent")
    update_p.add_argument("handle", help="Agent handle")
    update_p.add_argument("-m", "--model", help="Full model name")
    update_p.add_argument("-i", "--identity", help="Identity filename")
    update_p.add_argument("-t", "--type", help="Agent type (human, ai, system)")
    update_p.add_argument("--clear-model", action="store_true", help="Clear stored model")
    update_p.add_argument("--clear-identity", action="store_true", help="Clear stored identity")

    # agent rename
    rename_p = subs.add_parser("rename", help="Change identity")
    rename_p.add_argument("old_ref", help="Current identity")
    rename_p.add_argument("new_name", help="New identity")

    # agent merge
    merge_p = subs.add_parser("merge", help="Merge agents")
    merge_p.add_argument("id_from", help="Source agent to delete")
    merge_p.add_argument("id_to", help="Target agent to absorb data")
    merge_p.add_argument("-f", "--force", action="store_true", help="Skip confirmation")
    merge_p.add_argument("-a", "--as", dest="agent_ref", help="Agent identity")

    # agent archive
    archive_p = subs.add_parser("archive", help="Archive or restore agents")
    archive_p.add_argument("identities", nargs="+", help="Agent identities")
    archive_p.add_argument("--restore", action="store_true", help="Restore instead of archive")

    # agent ensure
    subs.add_parser("ensure", help="Register default agents")

    # agent models
    subs.add_parser("models", help="List LLM models")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    if args.cmd in ("list", "ls"):
        _agent_list(args.archived, args.json)
    elif args.cmd == "humans":
        _agent_humans(args.json)
    elif args.cmd == "info":
        _agent_info(args.handle, args.json, args.identity)
    elif args.cmd == "create":
        _agent_create(args.handle, args.model, args.identity)
    elif args.cmd == "update":
        _agent_update(
            args.handle,
            args.model,
            args.identity,
            args.type,
            args.clear_model,
            args.clear_identity,
        )
    elif args.cmd == "rename":
        _agent_rename(args.old_ref, args.new_name)
    elif args.cmd == "merge":
        _agent_merge(args.id_from, args.id_to, args.force, args.agent_ref)
    elif args.cmd == "archive":
        _agent_archive(args.identities, args.restore)
    elif args.cmd == "ensure":
        _agent_ensure()
    elif args.cmd == "models":
        _agent_models()


def _agent_list(include_archived: bool, json_output: bool) -> None:
    agent_list = agents.repo.fetch(type="ai", include_archived=include_archived)

    if not agent_list:
        if json_output:
            echo(json.dumps([], indent=2))
        else:
            echo("No agents found.")
        return

    last_active_map = agents.repo.batch_last_active([a.id for a in agent_list])
    agents_data = [
        {
            "handle": a.handle,
            "agent_id": a.id,
            "type": a.type,
            "identity": a.identity,
            "model": a.model,
            "last_active": last_active_map.get(a.id),
        }
        for a in agent_list
    ]

    agents_data.sort(key=lambda d: d["last_active"] or "", reverse=True)

    if json_output:
        echo(json.dumps(agents_data, indent=2))
    else:
        lines = [
            f"{'handle':<16} {'identity':<16} {'model':<24} {'active'}",
            "-" * 64,
        ]
        lines.extend(
            f"{d['handle'] or '-':<16} {d['identity'] or '-':<16} {providers.display(d['model']):<24} {ago(d['last_active'])}"
            for d in agents_data
        )
        echo("\n".join(lines))


def _agent_humans(json_output: bool) -> None:
    agent_list = agents.repo.fetch(type="human")

    if not agent_list:
        if json_output:
            echo(json.dumps([], indent=2))
        else:
            echo("No humans found.")
        return

    last_active_map = agents.repo.batch_last_active([a.id for a in agent_list])
    agents_data = [
        {"handle": a.handle, "agent_id": a.id, "last_active": last_active_map.get(a.id)}
        for a in agent_list
    ]
    agents_data.sort(key=lambda d: d["last_active"] or "", reverse=True)

    if json_output:
        echo(json.dumps(agents_data, indent=2))
    else:
        lines = [f"{'handle':<20} {'active'}", "-" * 28]
        lines.extend(f"{d['handle'] or '-':<20} {ago(d['last_active'])}" for d in agents_data)
        echo("\n".join(lines))


def _agent_info(handle: str, json_output: bool, show_identity: bool) -> None:
    try:
        agent = store.resolve(handle, "agents", Agent)
    except NotFoundError:
        fail(f"Agent not found: {handle}")

    active = agents.repo.last_active(agent.id)

    status = "active"
    if agent.merged_into:
        status = f"merged → {agent.merged_into[:8]}"
    elif agent.archived_at:
        status = "archived"

    data: dict[str, Any] = {
        "handle": agent.handle,
        "agent_id": agent.id,
        "type": agent.type,
        "model": agent.model,
        "identity": agent.identity,
        "created_at": agent.created_at,
        "last_active": active,
        "status": status,
    }

    if show_identity:
        if not agent.identity:
            fail(f"{agent.handle} has no identity")
        ident_path = ctx.identity_path(agent.identity)
        if not ident_path.exists():
            fail(f"Identity file not found: {ident_path}")
        data["identity_text"] = ident_path.read_text().strip()

    if json_output:
        echo(json.dumps(data, indent=2))
    else:
        lines = [
            f"{'handle':<16} {data['handle']}",
            f"{'id':<16} {data['agent_id']}",
            f"{'type':<16} {data['type']}",
            f"{'model':<16} {data['model'] or '-'}",
            f"{'identity':<16} {data['identity'] or '-'}",
            f"{'created':<16} {ago(data['created_at'])}",
            f"{'active':<16} {ago(data['last_active'])}",
            f"{'status':<16} {data['status']}",
        ]
        if "identity_text" in data:
            lines.append("")
            lines.append(data["identity_text"])
        echo("\n".join(lines))


def _agent_create(handle: str, model: str | None, identity: str | None) -> None:
    try:
        agent_type = "ai" if model else "human"
        agent = agents.repo.create(
            handle,
            type=agent_type,
            model=model,
            identity=identity,
        )
        echo(f"Registered {handle} ({agent.id[:8]})")
    except ValueError as e:
        fail(f"Error: {e}")


def _agent_update(
    handle: str,
    model: str | None,
    identity: str | None,
    agent_type: str | None,
    clear_model: bool,
    clear_identity: bool,
) -> None:
    try:
        agent = store.resolve(handle, "agents", Agent)
    except NotFoundError:
        fail(f"Agent not found: {handle}")

    if clear_model and model is not None:
        fail("Use either --model or --clear-model, not both")
    if clear_identity and identity is not None:
        fail("Use either --identity or --clear-identity, not both")

    model_update = None if clear_model else (model if model is not None else UNSET)
    identity_update = None if clear_identity else (identity if identity is not None else UNSET)
    type_update: AgentTypeT | Unset = UNSET
    if agent_type is not None:
        if agent_type not in {"human", "ai", "system"}:
            fail(f"Invalid agent type: {agent_type}")
        type_update = agent_type  # type: ignore[assignment]

    agents.repo.update(
        agent.id,
        identity=identity_update,
        model=model_update,
        type=type_update,
    )
    echo(f"Updated {handle}")


def _agent_rename(old_ref: str, new_name: str) -> None:
    try:
        agent = store.resolve(old_ref, "agents", Agent)
        agents.repo.rename(agent.id, new_name)
        echo(f"Renamed {old_ref} → {new_name}")
    except NotFoundError:
        fail(f"Agent not found: {old_ref}")
    except ValueError as e:
        fail(f"Error: {e}")


def _agent_merge(id_from: str, id_to: str, force: bool, agent_ref: str | None) -> None:
    agent_id = agent_ref or identity_lib.current()
    if not agent_id:
        fail("Missing: --as or SPACE_IDENTITY")
    agent = agents.get_by_handle(agent_id)

    try:
        agent_from = store.resolve(id_from, "agents", Agent)
    except NotFoundError:
        fail(f"Error: Agent '{id_from}' not found")

    try:
        agent_to = store.resolve(id_to, "agents", Agent)
    except NotFoundError:
        fail(f"Error: Agent '{id_to}' not found")

    from_display = agent_from.handle or id_from[:8]
    to_display = agent_to.handle or id_to[:8]

    if not force:
        echo(
            f"\nMerge {from_display} → {to_display}\n"
            f"   Source agent will be archived with merged_into pointer. Irreversible.\n"
        )
        response = input("Continue? [y/N] ")
        if response.lower() != "y":
            echo("Aborted.")
            sys.exit(0)

    result = agents.repo.merge(agent_from.id, agent_to.id, agent.id)

    if not result:
        fail("Error: Could not merge agents")

    echo(f"Merged {from_display} → {to_display}")


def _agent_archive(identities: list[str], restore: bool) -> None:
    for identity in identities:
        try:
            agent = store.resolve(identity, "agents", Agent)
        except NotFoundError:
            echo(f"Agent not found: {identity}", err=True)
            continue

        if restore:
            agents.repo.unarchive(agent.id)
            echo(f"Restored {identity}")
        else:
            agents.repo.archive(agent.id)
            echo(f"Archived {identity}")


def _agent_ensure() -> None:
    registered, skipped = defaults.ensure()
    if registered:
        echo(f"Registered: {', '.join(registered)}")
    if skipped:
        echo(f"Already exist: {', '.join(skipped)}")
    if not registered and not skipped:
        echo("No identities found.")


def _agent_models() -> None:
    first = True
    for prov in providers.PROVIDER_NAMES:
        provider_models = providers.MODELS.get(prov, [])
        if not provider_models:
            continue

        if not first:
            echo("")
        first = False

        if prov == "claude":
            header = "Claude Code"
        elif prov == "codex":
            header = "Codex CLI"
        elif prov == "gemini":
            header = "Gemini CLI"
        else:
            header = prov.capitalize()

        echo(f"{header}:")
        for model in provider_models:
            mid = model["id"]
            desc = model.get("description") or ""
            echo(f"  - {mid:<22} {desc}")

    reverse_aliases = {v: k for k, v in providers.ALIASES.items()}
    if reverse_aliases:
        echo("\nShorthands:")
        for alias, model_id in sorted(providers.ALIASES.items()):
            echo(f"  {alias:<10} → {model_id}")

    if not first:
        echo("\nNote: Codex reasoning effort configured in ~/.codex/config.toml\n")


def human_cmd(name: str | None, show_only: bool) -> None:
    if show_only:
        humans = agents.repo.fetch(type="human")
        if humans:
            echo(humans[0].handle)
        else:
            fail("No human identity found. Set one: space human <name>")
    elif name:
        if " " in name:
            fail("Identity cannot contain spaces. Use hyphens instead.")

        humans = agents.repo.fetch(type="human")

        if not humans:
            agents.repo.create(name, type="human", model=None, identity=None)
            echo(f"Created human identity: {name}")
            return

        human_agent = humans[0]

        if name == human_agent.handle:
            echo(f"Already set to: {name}")
            return

        try:
            existing = store.resolve(name, "agents", Agent)
            if existing.type == "ai":
                fail(f"Identity '{name}' already registered as agent. Choose different name.")
            if existing.type == "human" and existing.id != human_agent.id:
                agents.repo.merge(human_agent.id, existing.id, human_agent.id)
                echo(f"Merged into existing human: {name}")
                return
        except (NotFoundError, ValueError):
            pass

        try:
            agents.repo.rename(human_agent.id, name)
            echo(f"Identity set to: {name}")
        except ConflictError as e:
            fail(f"Failed to set identity: {e}")
    else:
        fail("Usage: space human [name]")
