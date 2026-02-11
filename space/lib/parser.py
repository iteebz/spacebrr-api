import re

SPACE_COMMANDS = {
    "sleep",
    "ledger",
    "tail",
    "swarm",
    "agent",
    "spawn",
    "tree",
    "me",
    "human",
    "backup",
    "skill",
    "@",
    "stream",
    "status",
}

_BASH_PRIMITIVES: list[tuple[re.Pattern[str], str, str | None]] = [
    (re.compile(r"^cd\b"), "Cd", r"^cd\s+"),
    (re.compile(r"^space\s+(\S+)"), "_space", None),
    (re.compile(r"^git\b"), "Git", None),
    (re.compile(r"^rg\b"), "Grep", None),
    (re.compile(r"^(ls|exa)\b"), "LS", None),
    (re.compile(r"^curl\b"), "Fetch", None),
    (re.compile(r"^uv\s+run\s+"), "Run", r"^uv\s+run\s+"),
    (re.compile(r"^python[23]?\b"), "Run", None),
    (re.compile(r"^just\b"), "Run", None),
    (re.compile(r"^(npm|pnpm|yarn)\s+run\s+"), "Run", r"^(npm|pnpm|yarn)\s+run\s+"),
    (re.compile(r"^(npm|pnpm|yarn)\b"), "Run", None),
    (re.compile(r"^(make|cargo|go)\b"), "Run", None),
]

_STRIP_CACHE: dict[str, re.Pattern[str]] = {}


def _strip_re(pattern: str) -> re.Pattern[str]:
    if pattern not in _STRIP_CACHE:
        _STRIP_CACHE[pattern] = re.compile(pattern)
    return _STRIP_CACHE[pattern]


_CHAIN_RE = re.compile(r'\s*&&\s*(?=(?:[^"]*"[^"]*")*[^"]*$)(?=(?:[^\']*\'[^\']*\')*[^\']*$)')


def split_chain(cmd: str) -> list[str]:
    parts = _CHAIN_RE.split(cmd.strip())
    return [p.strip() for p in parts if p.strip()]


_CD_RE = re.compile(r"^cd\s+(.+)")


def extract_cd(cmd: str) -> str | None:
    for sub in split_chain(cmd.strip()):
        m = _CD_RE.match(sub.strip())
        if m:
            return m.group(1).strip().strip("'\"")
    return None


def parse_bash(cmd: str) -> tuple[str, str]:
    cleaned = cmd.strip()
    for pat, name, strip in _BASH_PRIMITIVES:
        m = pat.match(cleaned)
        if not m:
            continue
        if name == "_space":
            sub = m.group(1)
            if sub in SPACE_COMMANDS:
                return sub.capitalize(), cleaned[m.end() :].strip()
            break
        arg = _strip_re(strip).sub("", cleaned).strip() if strip else cleaned
        return name, arg
    parts = cleaned.split(maxsplit=2)
    if parts and parts[0] in SPACE_COMMANDS:
        return parts[0].capitalize(), " ".join(parts[1:]) if len(parts) > 1 else ""
    return "Run", cleaned
