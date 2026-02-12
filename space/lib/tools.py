import argparse
import json
import sys
from enum import StrEnum
from typing import Any

from space.lib.commands import echo, space_cmd


class Tool(StrEnum):
    SHELL = "shell"
    WRITE = "write"
    EDIT = "edit"
    READ = "read"
    LS = "ls"
    GLOB = "glob"
    GREP = "grep"
    FETCH = "fetch"
    SEARCH = "search"


ALL_TOOLS = frozenset(Tool)

PROVIDER_TOOLS: dict[str, dict[Tool, list[str]]] = {
    "claude": {
        Tool.SHELL: ["Bash"],
        Tool.WRITE: ["Write"],
        Tool.EDIT: ["Edit", "MultiEdit"],
        Tool.READ: ["Read"],
        Tool.LS: ["LS"],
        Tool.GLOB: ["Glob"],
        Tool.GREP: ["Grep"],
        Tool.FETCH: ["WebFetch"],
        Tool.SEARCH: ["WebSearch"],
    },
    "gemini": {
        Tool.SHELL: ["run_shell_command"],
        Tool.WRITE: ["write_file"],
        Tool.EDIT: ["replace"],
        Tool.READ: ["read_file"],
        Tool.LS: ["list_directory"],
        Tool.GLOB: ["glob"],
        Tool.GREP: ["search_file_content"],
        Tool.FETCH: ["web_fetch"],
        Tool.SEARCH: ["google_web_search"],
    },
    "codex": {
        Tool.SHELL: ["Bash"],
    },
}

ALWAYS_DISALLOWED: dict[str, list[str]] = {
    "claude": ["NotebookRead", "NotebookEdit", "Task", "TodoWrite"],
    "gemini": [],
    "codex": [],
}


def all_provider_tools(provider: str) -> set[str]:
    mapping = PROVIDER_TOOLS.get(provider, {})
    return {tool for tools in mapping.values() for tool in tools}


def disallowed_for(provider: str, allowed: set[Tool] | None = None) -> list[str]:
    base_disallowed = set(ALWAYS_DISALLOWED.get(provider, []))

    if allowed is None:
        return sorted(base_disallowed)

    mapping = PROVIDER_TOOLS.get(provider, {})
    all_tools = all_provider_tools(provider)
    allowed_tools = {t for cap in allowed for t in mapping.get(cap, [])}

    return sorted(base_disallowed | (all_tools - allowed_tools))


def allowed_for(provider: str, allowed: set[Tool] | None = None) -> list[str]:
    if allowed is None:
        mapping = PROVIDER_TOOLS.get(provider, {})
        return sorted({t for tools in mapping.values() for t in tools})

    mapping = PROVIDER_TOOLS.get(provider, {})
    return sorted({t for cap in allowed for t in mapping.get(cap, [])})


def parse_tools(tools_list: list[str] | None) -> set[Tool] | None:
    if tools_list is None:
        return None
    result = set()
    for t in tools_list:
        try:
            result.add(Tool(t.lower()))
        except ValueError:
            continue
    return result if result else None


def _provider_tool_to_capability(provider: str) -> dict[str, Tool]:
    mapping = PROVIDER_TOOLS.get(provider, {})
    inverted: dict[str, Tool] = {}
    for cap, tool_names in mapping.items():
        for tool_name in tool_names:
            inverted[tool_name] = cap
    return inverted


def tool_name_map(provider: str, canonical_provider: str = "claude") -> dict[str, str]:
    if provider == canonical_provider:
        return {}

    provider_to_cap = _provider_tool_to_capability(provider)
    canonical = PROVIDER_TOOLS.get(canonical_provider, {})

    out: dict[str, str] = {}
    for provider_tool, cap in provider_to_cap.items():
        canonical_names = canonical.get(cap, [])
        if canonical_names:
            out[provider_tool] = canonical_names[0]
    return out


def normalize_tool_name(
    provider: str, tool_name: str, *, canonical_provider: str = "claude"
) -> str:
    return tool_name_map(provider, canonical_provider).get(tool_name, tool_name)


def _mapping_payload(*, provider: str | None = None) -> dict[str, Any]:
    providers = [provider] if provider else sorted(PROVIDER_TOOLS.keys())
    out: dict[str, Any] = {}

    for p in providers:
        caps = PROVIDER_TOOLS.get(p, {})
        out[p] = {
            "capabilities": {cap.value: list(tool_names) for cap, tool_names in caps.items()},
            "always_disallowed": list(ALWAYS_DISALLOWED.get(p, [])),
        }

    return out


@space_cmd("tools")
def main() -> None:
    parser = argparse.ArgumentParser(prog="tools", description="Manage provider tool mappings")
    subs = parser.add_subparsers(dest="cmd")

    mapping_p = subs.add_parser("mapping", help="Show provider→capability→tool-name mappings")
    mapping_p.add_argument("-p", "--provider", help="Limit to a single provider")
    mapping_p.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    disallowed_p = subs.add_parser("disallowed", help="Compute provider deny list")
    disallowed_p.add_argument("provider", help="Provider name (claude|gemini|codex)")
    disallowed_p.add_argument("-t", "--tools", help="Comma-separated capabilities")
    disallowed_p.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    normalize_p = subs.add_parser("normalize", help="Normalize provider tool name")
    normalize_p.add_argument("provider", help="Provider name")
    normalize_p.add_argument("tool_name", help="Provider tool name")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    if args.cmd == "mapping":
        payload = _mapping_payload(provider=args.provider)
        if args.json:
            echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for p in sorted(payload.keys()):
                echo(f"[{p}]")
                caps: dict[str, list[str]] = payload[p]["capabilities"]
                for cap in sorted(caps.keys()):
                    echo(f"  {cap}: {', '.join(caps[cap])}")
                disallowed = payload[p].get("always_disallowed") or []
                if disallowed:
                    echo(f"  always_disallowed: {', '.join(disallowed)}")
                echo("")

    elif args.cmd == "disallowed":
        allowed: set[Tool] | None = None
        if args.tools:
            allowed = {Tool(t.strip().lower()) for t in args.tools.split(",") if t.strip()}
        deny = disallowed_for(args.provider, allowed)
        if args.json:
            echo(json.dumps({"provider": args.provider, "disallowed": deny}, indent=2))
        else:
            for name in deny:
                echo(name)

    elif args.cmd == "normalize":
        echo(normalize_tool_name(args.provider, args.tool_name))
