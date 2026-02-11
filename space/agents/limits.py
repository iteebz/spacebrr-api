import argparse
import json
from typing import Any

from space.lib.commands import echo, space_cmd
from space.lib.providers import limits


def _limits_payload(data: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "provider": p.provider,
            "error": p.error,
            "buckets": [
                {
                    "name": b.name,
                    "used_pct": b.used_pct,
                    "remaining_pct": b.remaining_pct,
                    "resets_at": b.resets_at.isoformat() if b.resets_at else None,
                }
                for b in p.buckets
            ],
        }
        for p in data
    ]


@space_cmd("limits")
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provider usage limits (Claude Code 5h/weekly, Codex)."
    )
    parser.add_argument("-j", "--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    data = limits.all_providers()

    if args.json:
        echo(json.dumps(_limits_payload(data), indent=2))
    else:
        echo(limits.format_limits(data))
