import difflib
import re
from pathlib import Path

from space.lib.display import ansi, format_nameplate
from space.lib.parser import parse_bash as parse_bash_display
from space.lib.parser import split_chain
from space.lib.providers import base as provider_base

_HOME = str(Path.home())
_CWD = str(Path.cwd())

WAKE_PHRASES = (
    "~ waking",
    "~ stretching",
    "~ yawning",
    "~ brring",
    "~ humming",
    "~ blinking",
    "~ stirring",
    "~ flopping",
)

TOOL_DISPLAY = {
    "WebFetch": "Fetch",
    "WebSearch": "Web",
    "MultiEdit": "Edit",
    "Reply": "Re",
}

_RUN_NAMES = {"Run", "Git", "Sleep", "Spawn", "Agent", "Project", "Scenario"}
_GOLD_NAMES = {"Task", "Decision", "Insight", "Re", "Skill", "Show"}

TOOL_COLORS = {
    "Write": ansi.lime,
    "Edit": ansi.lime,
    "Run": ansi.blue,
    "Cd": ansi.white,
    "Git": ansi.purple,
    "Read": ansi.teal,
    "Grep": ansi.teal,
    "Glob": ansi.teal,
    "LS": ansi.teal,
    "Fetch": ansi.teal,
    "Web": ansi.teal,
    "Search": ansi.teal,
    "Show": ansi.gold,
    "Skill": ansi.gold,
    "Task": ansi.gold,
    "Decision": ansi.gold,
    "Insight": ansi.white,
    "Re": ansi.peach,
}

_DOMAIN_RE = re.compile(r"(?:--domain|-d)\s+(\S+)")


def _format_insight_arg(arg: str) -> str:
    m = _DOMAIN_RE.search(arg)
    if m:
        domain = m.group(1).strip('"').strip("'")
        return (
            ansi.gray(arg[: m.start()])
            + ansi.bold(ansi.white(f"#{domain}"))
            + ansi.gray(arg[m.end() :])
        )
    return ansi.gray(arg)


def tool_arg(raw_name: str, inp: dict[str, object]) -> str:
    if raw_name == "WebFetch":
        return str(inp.get("url", ""))
    if raw_name == "WebSearch":
        return str(inp.get("query", ""))

    command = inp.get("command")
    if isinstance(command, str) and command:
        return command

    path = inp.get("path") or inp.get("file_path")
    pattern = inp.get("pattern")

    if raw_name == "Grep":
        if isinstance(path, str) and isinstance(pattern, str) and path and pattern:
            return f"{path} {pattern}"
        if isinstance(pattern, str) and pattern:
            return pattern
        if isinstance(path, str):
            return path

    if isinstance(path, str) and path:
        return path
    if isinstance(pattern, str) and pattern:
        return pattern

    query = inp.get("query")
    if isinstance(query, str):
        return query
    url = inp.get("url")
    if isinstance(url, str):
        return url
    return ""


def format_tool_arg(name: str, arg: str, *, inp: dict[str, object] | None = None) -> str:
    if name in _RUN_NAMES:
        return ansi.slate(f"`{ansi.highlight_references(arg, ansi.DEFAULT.slate)}`")
    if name == "Insight":
        return _format_insight_arg(arg)
    if name in _GOLD_NAMES:
        return ansi.white(ansi.highlight_references(arg, ansi.DEFAULT.white))
    if name == "Grep" and inp:
        pattern = inp.get("pattern", "")
        if isinstance(pattern, str) and pattern:
            path = inp.get("path") or inp.get("file_path") or ""
            path = str(path).replace(_CWD, ".").replace(_HOME, "~") if path else ""
            pattern_fmt = ansi.highlight_references(pattern, ansi.DEFAULT.white)
            return (
                (ansi.blue(path) + " " + ansi.white(pattern_fmt))
                if path
                else ansi.white(pattern_fmt)
            )
    if "/" in arg or "~" in arg:
        return ansi.highlight_references(
            ansi.highlight_path(arg, ansi.DEFAULT.white), ansi.DEFAULT.white
        )
    return ansi.white(ansi.highlight_references(arg, ansi.DEFAULT.white))


def edit_suffix(raw_name: str, inp: dict[str, object], verbose: bool = False) -> str:
    name = TOOL_DISPLAY.get(raw_name, raw_name)
    if name in ("Edit", "MultiEdit"):
        edits_raw = inp.get("edits", [])
        edits_list: list[dict[str, object]] = list(edits_raw) if isinstance(edits_raw, list) else []
        if raw_name == "Edit":
            edits_list = [
                {"old_string": inp.get("old_string", ""), "new_string": inp.get("new_string", "")}
            ]
        total_add, total_rem = 0, 0
        all_diff_lines: list[str] = []
        for edit in edits_list:
            old = edit.get("old_string", "")
            new = edit.get("new_string", "")
            if isinstance(old, str) and isinstance(new, str):
                old_lines = old.rstrip().split("\n") if old else []
                new_lines = new.rstrip().split("\n") if new else []
                for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0):
                    if line.startswith(("---", "+++", "@@")):
                        continue
                    if line.startswith("-"):
                        total_rem += 1
                        if verbose:
                            all_diff_lines.append(f"          {ansi.red(line)}")
                    elif line.startswith("+"):
                        total_add += 1
                        if verbose:
                            all_diff_lines.append(f"          {ansi.green(line)}")
                    elif verbose:
                        all_diff_lines.append(f"          {ansi.gray(line)}")
        parts = []
        if total_add > 0:
            parts.append(ansi.lime(f"+{total_add}"))
        if total_rem > 0:
            parts.append(ansi.coral(f"-{total_rem}"))
        suffix = f" ({' '.join(parts)})" if parts else ""
        if all_diff_lines:
            suffix += "\n" + "\n".join(all_diff_lines)
        return suffix
    if name == "Write":
        content = inp.get("content", "")
        if isinstance(content, str):
            add = len(content.split("\n"))
            suffix = f" ({ansi.lime(f'+{add}')})"
            if verbose:
                lines = content.rstrip().split("\n")
                diff_lines = [f"          {ansi.green('+' + line)}" for line in lines]
                suffix += "\n" + "\n".join(diff_lines)
            return suffix
    return ""


def normalize_raw(d: dict[str, object]) -> dict[str, object] | None:
    etype = d.get("type")
    if etype == "assistant":
        msg = d.get("message")
        content = msg.get("content", []) if isinstance(msg, dict) else []
        if not content:
            return None
        c = content[0]
        if c.get("type") == "text":
            return {"type": "text", "content": c.get("text", "")}
        if c.get("type") == "tool_use":
            return {
                "type": "tool_call",
                "content": {
                    "tool_name": c.get("name", "?"),
                    "input": c.get("input", {}),
                    "tool_use_id": c.get("id", ""),
                },
            }
    if etype == "result":
        sub = d.get("subtype", "done")
        if sub == "error":
            output = d.get("output", "") or d.get("error", "") or d.get("reason", "")
            return {
                "type": "tool_result",
                "content": {"output": output, "is_error": True, "tool_use_id": ""},
            }
    return None


def format_event(
    d: dict[str, object],
    identity: str,
    ctx_pct: float | None = None,
    verbose: bool = False,
    tool_map: dict[str, str] | None = None,
    identities: set[str] | None = None,
) -> str | None:
    etype = d.get("type")
    if etype not in ("text", "tool_call", "tool_result"):
        d = normalize_raw(d) or d
        etype = d.get("type")

    prefix = format_nameplate(identity, ctx_pct)
    content = d.get("content")

    if etype == "text":
        text = provider_base.stringify_content(content)
        text = text.replace(_CWD, ".").replace(_HOME, "~")
        if verbose:
            text = text.replace("\n", " ")
            text = ansi.strip_markdown(text)
            text = ansi.highlight_references(text, ansi.DEFAULT.forest)
            line = f"{prefix} {ansi.bold(ansi.green('hm...'))} {ansi.forest(text)}"
        else:
            text = text.replace("\n", " ")
            text = ansi.strip_markdown(text)
            m = re.search(r"[\.\?\!](?:\s|$)", text)
            if m:
                text = text[: m.start() + 1]
            elif len(text) > 120:
                text = text[:120] + "…"
            text = ansi.highlight_references(text.lower(), ansi.DEFAULT.forest)
            line = f"{prefix} {ansi.bold(ansi.green('hm...'))} {ansi.forest(text)}"
        return line

    if etype == "tool_call" and isinstance(content, dict):
        raw_name = str(content.get("tool_name") or "?")
        name: str = TOOL_DISPLAY.get(raw_name, raw_name)
        inp = content.get("input", {}) if isinstance(content.get("input", {}), dict) else {}
        arg = tool_arg(raw_name, inp)
        arg = arg.replace(_CWD, ".").replace(_HOME, "~")
        if not verbose:
            arg = arg.split("\n")[0]
        is_bash = raw_name == "Bash"
        if is_bash:
            name, arg = parse_bash_display(arg)
            name = TOOL_DISPLAY.get(name, name)
        suffix = edit_suffix(raw_name, inp, verbose=verbose)
        color = TOOL_COLORS.get(name, ansi.gray)
        label = ansi.bold(color(name.lower()))
        arg_fmt = format_tool_arg(name, arg, inp=inp)
        return f"{prefix} {label} {arg_fmt}{suffix}"

    if etype == "tool_result" and isinstance(content, dict):
        is_error = bool(content.get("is_error", False))
        if is_error:
            tool_use_id = content.get("tool_use_id", "")
            tool_name = ""
            if tool_map and isinstance(tool_use_id, str):
                raw_name = tool_map.get(tool_use_id, "")
                tool_name = TOOL_DISPLAY.get(raw_name, raw_name)
            output = content.get("output", "")
            if isinstance(output, str) and output.strip().lower() not in ("", "error"):
                err_line = output.replace(_HOME, "~").split("\n")[0][:80]
                err_line = ansi.highlight_references(err_line, ansi.DEFAULT.coral)
                err_label = f"{tool_name.lower()} " if tool_name else ""
                return f"{prefix} {ansi.bold(ansi.red('oops.'))} {ansi.coral(err_label + err_line)}"
            err_label = tool_name.lower() if tool_name else "unknown tool"
            return f"{prefix} {ansi.bold(ansi.red('oops.'))} {ansi.coral(err_label)}"
        return None

    return None


def _format_bash_chain(
    d: dict[str, object],
    identity: str,
    ctx_pct: float | None = None,
    verbose: bool = False,
    identities: set[str] | None = None,
) -> list[str]:
    content = d.get("content")
    if not isinstance(content, dict):
        return []
    raw_name = str(content.get("tool_name") or "?")
    if raw_name != "Bash":
        return []
    inp = content.get("input", {}) if isinstance(content.get("input", {}), dict) else {}
    cmd = tool_arg(raw_name, inp)
    cmd = cmd.replace(_CWD, ".").replace(_HOME, "~").split("\n")[0]
    subcmds = split_chain(cmd)
    if len(subcmds) <= 1:
        return []
    prefix = format_nameplate(identity, ctx_pct)
    lines: list[str] = []
    for sub in subcmds:
        name, arg = parse_bash_display(sub)
        name = TOOL_DISPLAY.get(name, name)
        color = TOOL_COLORS.get(name, ansi.gray)
        label = ansi.bold(color(name.lower()))
        arg_fmt = format_tool_arg(name, arg)
        line = f"{prefix} {label} {arg_fmt}"
        lines.append(line)
    return lines


def format_event_multi(
    d: dict[str, object],
    identity: str,
    ctx_pct: float | None = None,
    verbose: bool = False,
    tool_map: dict[str, str] | None = None,
    identities: set[str] | None = None,
) -> list[str]:
    etype = d.get("type")
    if etype not in ("text", "tool_call", "tool_result"):
        d = normalize_raw(d) or d
        etype = d.get("type")
    if etype == "tool_call":
        chain = _format_bash_chain(d, identity, ctx_pct, verbose, identities)
        if chain:
            return chain
    single = format_event(d, identity, ctx_pct, verbose, tool_map, identities)
    return [single] if single else []
