import argparse
import json
import random
import sys
import time
from datetime import UTC, datetime

from space import agents
from space.agents import daemon, spawn, swarm
from space.core.models import Agent, Spawn, SpawnStatus
from space.core.types import AgentId, SpawnId
from space.lib import config, providers, store, trace
from space.lib.commands import echo, fail, space_cmd
from space.lib.display import ansi
from space.lib.display import format as fmt
from space.lib.launch import sync_bin_scripts


def _split_list(items: list[str] | None) -> list[str] | None:
    if not items:
        return None
    if items == ["None"] or items == ["none"]:
        return None
    result = []
    for item in items:
        result.extend(
            x.strip() for x in item.split(",") if x.strip() and x.strip().lower() != "none"
        )
    return result or None


def _derive_filter_updates(
    agent_list: list[str] | None,
    provider_list: list[str] | None,
) -> tuple[list[str] | None, list[str] | None, bool, bool]:
    agent_filter = _split_list(agent_list)
    provider_filter = _split_list(provider_list)
    if provider_filter:
        invalid = [p for p in provider_filter if p not in providers.PROVIDER_NAMES]
        if invalid:
            fail(
                f"Unknown providers: {', '.join(invalid)}. Valid: {', '.join(providers.PROVIDER_NAMES)}"
            )

    agent_flag_passed = agent_list is not None
    provider_flag_passed = provider_list is not None
    reset_agents = (agent_flag_passed and agent_filter is None) or (
        not agent_flag_passed and not provider_flag_passed
    )
    reset_providers = (provider_flag_passed and provider_filter is None) or (
        not agent_flag_passed and not provider_flag_passed
    )
    return agent_filter, provider_filter, reset_agents, reset_providers


SLEEPY_BRRS = [
    "~brr... brr... (yawn)~",
    "~zzz... brr... zzz~",
    "~brr.......... brr..~",
    "~(sleepy brr noises)~",
    "~brr~ ...goodnight",
]


def _format_brr(cfg: config.SwarmConfig) -> str:
    c = cfg.concurrency or 1
    cap = f"+{cfg.limit}" if cfg.limit else "\u221e"
    agent_str = f" [{', '.join(cfg.agents)}]" if cfg.agents else ""
    return ansi.gray(f"{c}x {cap}{agent_str}")


def _format_config_parts(cfg: config.SwarmConfig, include_agents_all: bool = False) -> list[str]:
    parts = []
    if cfg.limit:
        parts.append(f"limit: {cfg.limit}")
    if cfg.concurrency > 1:
        parts.append(f"concurrency: {cfg.concurrency}")
    if cfg.agents:
        parts.append(f"agents: {', '.join(cfg.agents)}")
    elif include_agents_all:
        parts.append("agents: all")
    if cfg.providers:
        parts.append(f"providers: {', '.join(cfg.providers)}")
    return parts


def _fetch_crashed(
    agent_id: AgentId | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> list[Spawn]:
    return spawn.fetch(
        agent_id=agent_id,
        status=SpawnStatus.DONE,
        has_session=True,
        errors=daemon.CRASH_ERRORS,
        since=since,
        limit=limit,
    )


@space_cmd("swarm")
def main() -> None:
    parser = argparse.ArgumentParser(prog="swarm", description="Daemon control")
    subs = parser.add_subparsers(dest="cmd")

    dash_p = subs.add_parser("dash", help="Swarm dashboard")
    dash_p.add_argument("-w", "--watch", action="store_true", help="Live-updating display")
    dash_p.add_argument("-j", "--json", action="store_true", dest="json_output", help="JSON output")

    on_p = subs.add_parser("on", help="Enable autonomous agent wakes")
    on_p.add_argument("-n", "--limit", type=int, help="Stop after N spawns")
    on_p.add_argument("-c", "--concurrency", type=int, help="Max concurrent spawns")
    on_p.add_argument("-a", "--agents", nargs="*", help="Allowed agents")
    on_p.add_argument("-p", "--providers", nargs="*", help="Allowed providers")
    on_p.add_argument("--project", help="Filter to project scope")
    on_p.add_argument("-q", "--no-tail", action="store_true", help="Don't auto-tail")
    on_p.add_argument("-j", "--json", action="store_true", dest="json_output", help="JSON output")

    off_p = subs.add_parser("off", help="Disable autonomous agent wakes")
    off_p.add_argument("-j", "--json", action="store_true", dest="json_output", help="JSON output")

    reset_p = subs.add_parser("reset", help="Terminate active spawns and restart daemon")
    reset_p.add_argument(
        "-j", "--json", action="store_true", dest="json_output", help="JSON output"
    )

    status_p = subs.add_parser("status", help="Show autonomous spawn status")
    status_p.add_argument(
        "-j", "--json", action="store_true", dest="json_output", help="JSON output"
    )

    continue_p = subs.add_parser("continue", help="Resume crashed spawns")
    continue_p.add_argument("-a", "--agent", nargs="*", help="Filter by agents")
    continue_p.add_argument("-s", "--since", help="Time window (e.g. 1h, 1d)")
    continue_p.add_argument("-n", "--limit", type=int, default=10, help="Max spawns to resume")
    continue_p.add_argument("-d", "--dry-run", action="store_true", help="List without resuming")
    continue_p.add_argument(
        "-j", "--json", action="store_true", dest="json_output", help="JSON output"
    )

    replay_p = subs.add_parser("replay", help="Replay historical spawn session")
    replay_p.add_argument("spawn_id", nargs="?", help="Spawn ID to replay")
    replay_p.add_argument("-s", "--speed", type=float, default=10.0, help="Playback speed")
    replay_p.add_argument("--no-delay", action="store_true", help="Play all events instantly")
    replay_p.add_argument("-a", "--agent", help="Replay last spawn from agent")

    tail_p = subs.add_parser("tail", help="Live tail of spawn logs")
    tail_p.add_argument("agent", nargs="?", help="Filter to specific agent")
    tail_p.add_argument("-n", "--lines", type=int, default=20, help="Initial lines to show")
    tail_p.add_argument("-v", "--verbose", action="store_true", help="Show edit diffs")
    tail_p.add_argument("-s", "--since", type=int, default=10, help="Minutes of history")
    tail_p.add_argument("-w", "--watch", action="store_true", help="Continue streaming")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    if args.cmd == "dash":
        _dash(args.watch, args.json_output)
    elif args.cmd == "tail":
        _tail(args.agent, args.lines, args.verbose, args.since, args.watch)
    elif args.cmd == "on":
        _on(
            args.limit,
            args.concurrency,
            args.agents,
            args.providers,
            args.project,
            args.no_tail,
            args.json_output,
        )
    elif args.cmd == "off":
        _off(args.json_output)
    elif args.cmd == "reset":
        _reset(args.json_output)
    elif args.cmd == "status":
        _status(args.json_output)
    elif args.cmd == "continue":
        _continue(args.agent, args.since, args.limit, args.dry_run, args.json_output)
    elif args.cmd == "replay":
        _replay(args.spawn_id, args.speed, args.no_delay, args.agent)


def _dash(watch: bool, json_output: bool) -> None:
    if watch:
        _watch_loop(json_output)
    else:
        _render_snapshot(json_output=json_output)


def _watch_loop(json_output: bool = False) -> None:
    frame = 0
    try:
        sys.stdout.write(ansi.hide_cursor() + ansi.clear_screen())
        sys.stdout.flush()
        while True:
            sys.stdout.write(ansi.cursor_home())
            sys.stdout.flush()
            _render_snapshot(frame=frame, json_output=json_output)
            sys.stdout.write(ansi.clear_to_end())
            sys.stdout.flush()
            frame += 1
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(ansi.show_cursor())
        sys.stdout.flush()


def _render_snapshot(frame: int | None = None, json_output: bool = False) -> None:
    if json_output:
        echo(json.dumps(swarm.dash(json=True), indent=2))
        return

    for line in swarm.dash(frame=frame):
        echo(line)


def _on(
    limit: int | None,
    concurrency: int | None,
    agent_list: list[str] | None,
    provider_list: list[str] | None,
    project: str | None,
    quiet: bool,
    json_output: bool,
) -> None:
    sync_bin_scripts()

    _killed, reaped = spawn.reconcile()
    if reaped:
        echo(f"{ansi.mention('daemon')} {ansi.gray(f'reaped {reaped} orphaned spawns')}")

    agent_filter, provider_filter, reset_agents, reset_providers = _derive_filter_updates(
        agent_list, provider_list
    )
    was_off = daemon.on(
        limit,
        concurrency,
        agent_filter,
        providers_list=provider_filter,
        project=project,
        reset_agents=reset_agents,
        reset_providers=reset_providers,
        restart_daemon=True,
    )

    cfg = config.load().swarm
    if was_off:
        msg = f"{ansi.mention('daemon')} {ansi.lime('enabled')} {_format_brr(cfg)}"
    else:
        msg = f"{ansi.mention('daemon')} {_format_brr(cfg)}"
    json_data = {
        "enabled": True,
        "pid": daemon.pid(),
        "limit": cfg.limit,
        "concurrency": cfg.concurrency,
        "agents": cfg.agents,
        "providers": cfg.providers,
    }
    if json_output:
        echo(json.dumps(json_data, indent=2))
    else:
        echo(msg)
    if not quiet and not json_output:
        swarm.tail_spawns(watch=True)


def _off(json_output: bool) -> None:
    was_on = daemon.off()
    brr = random.choice(SLEEPY_BRRS) if was_on else "already off"  # noqa: S311
    msg = f"{ansi.mention('swarm')} {ansi.dim(brr)}"
    json_data = {"enabled": False, "pid": None}
    if json_output:
        echo(json.dumps(json_data, indent=2))
    else:
        echo(msg)


def _reset(json_output: bool) -> None:
    active = spawn.fetch(status=SpawnStatus.ACTIVE)
    for s in active:
        spawn.terminate(s.id)
    daemon_pid = daemon.start() if daemon.is_on() else None
    json_data = {"terminated": len(active), "pid": daemon_pid}
    if json_output:
        echo(json.dumps(json_data, indent=2))
    else:
        echo(f"reset {len(active)} spawns" + (f" (pid {daemon_pid})" if daemon_pid else ""))


def _status(json_output: bool) -> None:
    enabled = daemon.is_on()
    cfg = config.load().swarm

    blocked_providers = {}
    for provider_name in providers.PROVIDER_NAMES:
        blocked_until = providers.router.provider_blocked_until(provider_name)
        if blocked_until and blocked_until > datetime.now(UTC):
            blocked_providers[provider_name] = blocked_until.isoformat()

    data = {
        "enabled": enabled,
        "limit": cfg.limit,
        "concurrency": cfg.concurrency,
        "agents": cfg.agents,
        "providers": cfg.providers,
        "enabled_at": cfg.enabled_at,
        "blocked_providers": blocked_providers,
    }

    if json_output:
        echo(json.dumps(data, indent=2))
    elif not enabled:
        echo("off")
    else:
        parts = _format_config_parts(cfg)
        msg = f"on ({', '.join(parts)})" if parts else "on"
        echo(msg)
        if blocked_providers:
            echo("")
            for provider_name, until_iso in blocked_providers.items():
                until = datetime.fromisoformat(until_iso)
                delta = (until - datetime.now(UTC)).total_seconds()
                if delta < 60:
                    duration = f"{int(delta)}s"
                elif delta < 3600:
                    duration = f"{int(delta / 60)}m"
                else:
                    duration = f"{int(delta / 3600)}h{int((delta % 3600) / 60)}m"
                echo(f"  {ansi.amber(provider_name)} blocked for {duration}")


def _continue(
    agent_list: list[str] | None,
    since: str | None,
    limit: int,
    dry_run: bool,
    json_output: bool,
) -> None:
    since_iso: str | None = None
    if since:
        try:
            delta = fmt.parse_duration(since)
        except ValueError:
            fail(f"Invalid duration: {since}")
        since_iso = (datetime.now(UTC) - delta).isoformat()

    agent_identities = _split_list(agent_list)
    agent_ids = None
    if agent_identities:
        agent_ids = []
        for identity in agent_identities:
            try:
                agent = store.resolve(identity, "agents", Agent)
                agent_ids.append(agent.id)
            except Exception:
                fail(f"Agent not found: {identity}")

    crashed = _fetch_crashed(
        since=since_iso, limit=limit if not agent_ids else limit * len(agent_ids)
    )

    if agent_ids:
        crashed = [s for s in crashed if s.agent_id in agent_ids]

    seen_agents: set[str] = set()
    deduped = []
    for s in crashed:
        if s.agent_id not in seen_agents:
            seen_agents.add(s.agent_id)
            deduped.append(s)
    crashed = deduped

    if not crashed:
        if json_output:
            echo(json.dumps({"resumed": []}, indent=2))
        else:
            echo("no crashed spawns")
        return

    if dry_run:
        agent_map = agents.batch_get(list({s.agent_id for s in crashed}))
        lines = []
        for s in crashed:
            a = agent_map.get(s.agent_id)
            handle_str = a.handle if a else s.agent_id[:8]
            lines.append(f"  {store.ref('spawns', s.id)} @{handle_str} ({s.error})")
        echo(f"[CRASHED] ({len(crashed)})")
        for line in lines:
            echo(line)
        return

    resumed: list[dict[str, str]] = []
    for s in crashed[:limit]:
        agent_obj = agents.get(s.agent_id)
        try:
            spawn.launch(agent_id=agent_obj.id, spawn=s)
            resumed.append({"id": s.id, "handle": agent_obj.handle})
            echo(f"Resumed: {store.ref('spawns', s.id)} ({agent_obj.handle})")
        except Exception as e:
            echo(f"Failed: {store.ref('spawns', s.id)} - {e}")

    json_data = {"resumed": resumed}
    if json_output:
        echo(json.dumps(json_data, indent=2))
    else:
        echo(f"resumed {len(resumed)} spawns")


def _tail(
    agent: str | None,
    lines: int,
    verbose: bool,
    since: int,
    watch: bool,
) -> None:
    for line in swarm.tail_spawns(
        lines,
        agent,
        verbose=verbose,
        since_minutes=since,
        watch=watch,
    ):
        echo(line)


def _replay(spawn_id: str | None, speed: float, no_delay: bool, agent_filter: str | None) -> None:
    s: Spawn | None = None

    if agent_filter:
        agent = store.resolve(agent_filter, "agents", Agent)
        recent = spawn.fetch(agent_id=agent.id, limit=1)
        if not recent:
            fail(f"No spawns found for agent: {agent_filter}")
        s = recent[0]
    elif spawn_id:
        try:
            s = spawn.get(SpawnId(spawn_id))
        except Exception:
            fail(f"Spawn not found: {spawn_id}")
    else:
        recent = spawn.fetch(limit=1)
        if not recent:
            fail("No spawns found")
        s = recent[0]

    events_file = swarm.spawn_path_by_id(s.id)
    if not events_file:
        fail(f"No events file for spawn: {store.ref('spawns', s.id)}")

    agent = agents.get(s.agent_id)
    handle = agent.handle if agent else store.ref("spawns", s.id)

    events: list[tuple[datetime | None, dict[str, object], float | None]] = []
    ctx_pct: float | None = None

    with events_file.open() as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            try:
                d = json.loads(line)
                ts_str = d.get("timestamp")
                ts = datetime.fromisoformat(ts_str) if ts_str else None
                if (msg := d.get("message")) and (u := msg.get("usage")):
                    inp = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                    if inp > 0:
                        ctx_pct = max(0, 100 - inp / 200000 * 100)
                events.append((ts, d, ctx_pct))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

    if not events:
        fail("No events to replay")

    echo(ansi.dim(f"Replaying {handle} @ {speed}x ({len(events)} events)") + "\n")

    prev_ts: datetime | None = None
    try:
        for ts, event, pct in events:
            if not no_delay and ts and prev_ts:
                delta = (ts - prev_ts).total_seconds()
                if delta > 0:
                    time.sleep(min(delta / speed, 2.0))
            prev_ts = ts

            formatted = trace.format_event(event, handle, pct)
            if formatted:
                echo(formatted)
    except KeyboardInterrupt:
        echo("\n" + ansi.dim("[interrupted]"))

    echo("\n" + ansi.dim("[replay complete]"))
