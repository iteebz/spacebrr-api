import argparse
import json
from typing import Any

from space.agents.daemon import lifecycle as daemon_mod
from space.lib.commands import echo, fail, space_cmd


def _daemon_status() -> tuple[dict[str, Any], str]:
    pid = daemon_mod.pid()

    if pid:
        return {"running": True, "pid": pid}, f"running (pid {pid})"

    return {"running": False}, "stopped"


def _daemon_start() -> tuple[dict[str, Any], str]:
    existing_pid = daemon_mod.pid()
    if existing_pid:
        return {"started": False}, f"already running (pid {existing_pid})"
    pid = daemon_mod.start()
    return {"started": True, "pid": pid}, f"started (pid {pid})"


@space_cmd("daemon")
def main() -> None:
    """Manage daemon process."""
    parser = argparse.ArgumentParser(prog="daemon", description="Manage daemon process")
    parser.add_argument("action", nargs="?", default="status", help="start|stop|restart|status")
    parser.add_argument("-j", "--json", action="store_true", dest="json_output", help="Output JSON")

    args = parser.parse_args()

    if args.action == "status":
        payload, message = _daemon_status()
        if args.json_output:
            echo(json.dumps(payload, indent=2))
        else:
            echo(message)
    elif args.action == "start":
        payload, message = _daemon_start()
        if args.json_output:
            echo(json.dumps(payload, indent=2))
        else:
            echo(message)
    elif args.action == "stop":
        if daemon_mod.stop():
            if args.json_output:
                echo(json.dumps({"stopped": True}, indent=2))
            else:
                echo("stopped")
        else:
            if args.json_output:
                echo(json.dumps({"stopped": False}, indent=2))
            else:
                echo("not running")
    elif args.action == "restart":
        daemon_mod.stop()
        pid = daemon_mod.start()
        if args.json_output:
            echo(json.dumps({"restarted": True, "pid": pid}, indent=2))
        else:
            echo(f"restarted (pid {pid})")
    else:
        fail(f"Unknown action: {args.action}")
