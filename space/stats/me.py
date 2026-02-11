import argparse
import json
import sys

from space import stats
from space.lib.commands import echo, space_cmd
from space.lib.display import stats as stats_display


@space_cmd("me")
def main(hours: int = 24, json_output: bool = False) -> None:
    if hours == 24 and not json_output:
        parser = argparse.ArgumentParser(description="unified stats")
        parser.add_argument("-H", "--hours", type=int, default=24, help="time window")
        parser.add_argument("-j", "--json", action="store_true", help="output as JSON")

        if len(sys.argv) > 1 and sys.argv[1] == "me":
            args = parser.parse_args(sys.argv[2:])
            hours = args.hours
            json_output = args.json
        elif len(sys.argv) > 1:
            args = parser.parse_args()
            hours = args.hours
            json_output = args.json

    summary = stats.get_summary(hours)

    if json_output:
        echo(json.dumps(summary, indent=2))
    else:
        echo(stats_display.format_me(summary, hours))
