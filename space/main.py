"""Argparse entrypoint for human-facing commands (spec 08)."""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="space",
        description="Stateless agent, stateful swarm.",
    )
    subs = parser.add_subparsers(dest="command", help="Command to run")

    # 1. stream
    stream_p = subs.add_parser("stream", help="capture human consciousness")
    stream_p.add_argument("content", nargs="?", help="stream content (max 280 chars)")
    stream_p.add_argument("-p", "--project", help="project name")

    # 2. tail
    tail_p = subs.add_parser("tail", help="live tail of spawn logs")
    tail_p.add_argument("agent", nargs="?", help="filter to specific agent")
    tail_p.add_argument("-n", "--lines", type=int, default=20, help="initial lines to show")
    tail_p.add_argument("-v", "--verbose", action="store_true", help="show edit diffs")
    tail_p.add_argument("-s", "--since", type=int, default=10, help="minutes of history")
    tail_p.add_argument("-w", "--watch", action="store_true", help="follow mode")

    # 3. @
    at_p = subs.add_parser("@", help="route to entity")
    at_p.add_argument("target", help="agent identity or ref (i/xxx, d/xxx, t/xxx)")
    at_p.add_argument("message", help="message to send")
    at_p.add_argument("-m", "--model", help="model override")
    at_p.add_argument("-s", "--skills", help="comma-separated skills to inject")
    at_p.add_argument("-j", "--json", action="store_true", help="output as JSON")

    # 4. ledger
    ledger_p = subs.add_parser("ledger", help="unified ledger access")
    ledger_p.add_argument(
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
    ledger_p.add_argument("artifact", nargs="*", help="artifact type/ref/content")
    ledger_p.add_argument("-d", "--domain", help="domain for insight add")
    ledger_p.add_argument("-w", "--why", help="rationale for decision add")
    ledger_p.add_argument("-r", "--refs", help="references for decision add")
    ledger_p.add_argument("-o", "--outcome", help="outcome for decision action")
    ledger_p.add_argument("-n", "--limit", type=int, default=20, help="search result limit")
    ledger_p.add_argument("-g", "--all-projects", action="store_true", help="search all projects")
    ledger_p.add_argument("-j", "--json", action="store_true", help="output as JSON")

    # 5. swarm
    swarm_p = subs.add_parser("swarm", help="autonomous agent spawning")
    swarm_subs = swarm_p.add_subparsers(dest="swarm_cmd", help="swarm command")
    swarm_subs.add_parser("on", help="enable autonomous agent wakes")
    swarm_subs.add_parser("off", help="disable autonomous agent wakes")
    swarm_subs.add_parser("status", help="show autonomous spawn status")
    swarm_subs.add_parser("dash", help="swarm dashboard")
    swarm_subs.add_parser("reset", help="terminate active spawns and restart")
    swarm_subs.add_parser("continue", help="resume crashed spawns")

    # 6. spawn
    subs.add_parser("spawn", help="execution lifecycle")

    # 7. sleep
    sleep_p = subs.add_parser("sleep", help="close spawn with summary")
    sleep_p.add_argument("summary", nargs="?", help="what you accomplished")
    sleep_p.add_argument("-j", "--json", action="store_true", help="output as JSON")
    sleep_p.add_argument(
        "-f", "--force", action="store_true", help="sleep despite uncommitted changes"
    )

    # 8. status
    status_p = subs.add_parser("status", help="what needs doing")
    status_p.add_argument("-j", "--json", action="store_true", help="output as JSON")

    # 9. tree
    tree_p = subs.add_parser("tree", help="workspace topology")
    tree_p.add_argument("path", nargs="?", help="directory to tree")
    tree_p.add_argument("-j", "--json", action="store_true", help="output as JSON")

    # 10. me
    me_p = subs.add_parser("me", help="unified stats: human + swarm")
    me_p.add_argument("-H", "--hours", type=int, default=24, help="time window")
    me_p.add_argument("-j", "--json", action="store_true", help="output as JSON")

    # 11. human
    human_p = subs.add_parser("human", help="manage human identity")
    human_p.add_argument("name", nargs="?", help="show or set human identity")
    human_p.add_argument("--set", dest="set_name", help="explicitly set identity")

    # 12. backup
    subs.add_parser("backup", help="backup space data")

    args, _ = parser.parse_known_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "stream": lambda: __import__("space.agents.stream", fromlist=["main"]).main(args),
        "tail": lambda: __import__("space.agents.swarm", fromlist=["tail_spawns"]).tail_spawns(
            lines=args.lines,
            agent=args.agent,
            verbose=args.verbose,
            since_minutes=args.since,
            watch=args.watch,
        ),
        "@": lambda: __import__("space.agents.at", fromlist=["main"]).main(args),
        "ledger": lambda: __import__("space.ledger.cli", fromlist=["route"]).route(args),
        "swarm": lambda: __import__("space.agents.swarm", fromlist=["main"]).main(),
        "spawn": lambda: __import__("space.agents.spawn.cli", fromlist=["main"]).main(),
        "sleep": lambda: __import__("space.agents.sleep", fromlist=["main"]).main(
            summary=args.summary,
            json_output=args.json,
            force=args.force,
        ),
        "status": lambda: __import__("space.ledger.cli", fromlist=["status_cmd"]).status_cmd(
            identity=None,
            json_output=args.json,
        ),
        "tree": lambda: __import__("space.lib.tree", fromlist=["main"]).main(args),
        "me": lambda: __import__("space.stats.me", fromlist=["main"]).main(
            hours=args.hours,
            json_output=args.json,
        ),
        "backup": lambda: __import__("space.lib.backup", fromlist=["main"]).main(args),
        "human": lambda: __import__("space.agents.cli", fromlist=["human_cmd"]).human_cmd(
            name=args.set_name or args.name,
            show_only=args.set_name is None and args.name is None,
        ),
    }

    handler = handlers.get(args.command)
    if handler:
        handler()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
