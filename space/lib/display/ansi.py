import re
from dataclasses import dataclass

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class Theme:
    red: str = "\033[38;5;203m"
    green: str = "\033[38;5;114m"
    yellow: str = "\033[38;5;221m"
    blue: str = "\033[38;5;111m"
    magenta: str = "\033[38;5;176m"
    cyan: str = "\033[38;5;117m"
    gray: str = "\033[38;5;245m"
    white: str = "\033[38;5;252m"
    orange: str = "\033[38;5;208m"
    pink: str = "\033[38;5;212m"
    lime: str = "\033[38;5;155m"
    teal: str = "\033[38;5;80m"
    gold: str = "\033[38;5;220m"
    coral: str = "\033[38;5;209m"
    purple: str = "\033[38;5;141m"
    sky: str = "\033[38;5;67m"
    mint: str = "\033[38;5;121m"
    peach: str = "\033[38;5;217m"
    lavender: str = "\033[38;5;183m"
    slate: str = "\033[38;5;103m"
    sage: str = "\033[38;5;108m"
    forest: str = "\033[38;5;65m"
    amber: str = "\033[38;5;137m"
    mauve: str = "\033[38;5;139m"
    dim: str = "\033[2m"
    dim_off: str = "\033[22m"
    bold: str = "\033[1m"
    bold_off: str = "\033[22m"
    reset: str = "\033[0m"


DEFAULT = Theme()
_active: Theme = DEFAULT


def use(theme: Theme) -> None:
    global _active
    _active = theme


def strip(text: str) -> str:
    return _ANSI_RE.sub("", text)


_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_MD_CODE_RE = re.compile(r"`([^`]+)`")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_EMOJI_RE = re.compile(r"[✅🔲⬜]")


def strip_markdown(text: str) -> str:
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    return _MD_EMOJI_RE.sub("", text)


def red(text: str) -> str:
    return f"{_active.red}{text}{_active.reset}"


def green(text: str) -> str:
    return f"{_active.green}{text}{_active.reset}"


def yellow(text: str) -> str:
    return f"{_active.yellow}{text}{_active.reset}"


def blue(text: str) -> str:
    return f"{_active.blue}{text}{_active.reset}"


def magenta(text: str) -> str:
    return f"{_active.magenta}{text}{_active.reset}"


def cyan(text: str) -> str:
    return f"{_active.cyan}{text}{_active.reset}"


def gray(text: str) -> str:
    return f"{_active.gray}{text}{_active.reset}"


def white(text: str) -> str:
    return f"{_active.white}{text}{_active.reset}"


def orange(text: str) -> str:
    return f"{_active.orange}{text}{_active.reset}"


def pink(text: str) -> str:
    return f"{_active.pink}{text}{_active.reset}"


def lime(text: str) -> str:
    return f"{_active.lime}{text}{_active.reset}"


def teal(text: str) -> str:
    return f"{_active.teal}{text}{_active.reset}"


def gold(text: str) -> str:
    return f"{_active.gold}{text}{_active.reset}"


def coral(text: str) -> str:
    return f"{_active.coral}{text}{_active.reset}"


def purple(text: str) -> str:
    return f"{_active.purple}{text}{_active.reset}"


def sky(text: str) -> str:
    return f"{_active.sky}{text}{_active.reset}"


def mint(text: str) -> str:
    return f"{_active.mint}{text}{_active.reset}"


def peach(text: str) -> str:
    return f"{_active.peach}{text}{_active.reset}"


def lavender(text: str) -> str:
    return f"{_active.lavender}{text}{_active.reset}"


def slate(text: str) -> str:
    return f"{_active.slate}{text}{_active.reset}"


def sage(text: str) -> str:
    return f"{_active.sage}{text}{_active.reset}"


def amber(text: str) -> str:
    return f"{_active.amber}{text}{_active.reset}"


def mauve(text: str) -> str:
    return f"{_active.mauve}{text}{_active.reset}"


def forest(text: str) -> str:
    return f"{_active.forest}{text}{_active.reset}"


def dim(text: str) -> str:
    return f"{_active.dim}{text}{_active.dim_off}"


def bold(text: str) -> str:
    return f"{_active.bold}{text}{_active.bold_off}"


def clear_screen() -> str:
    return "\033[H\033[J"


def cursor_home() -> str:
    return "\033[H"


def clear_to_end() -> str:
    return "\033[J"


def hide_cursor() -> str:
    return "\033[?25l"


def show_cursor() -> str:
    return "\033[?25h"


def bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return f"{_active.lime}{'█' * filled}{_active.gray}{'░' * (width - filled)}{_active.reset}"


_PRIMITIVE_RE = re.compile(r"([itdr])/([a-f0-9]{8})")
_REFERENCE_RE = re.compile(r"(?<![a-zA-Z0-9_.:/-])([a-z])/([a-f0-9]{8})(?![a-zA-Z0-9_])")
_MENTION_RE = re.compile(r"@(\w+)")

_PATH_SEGMENT = r"[a-zA-Z0-9_.][a-zA-Z0-9_.-]*"
_PATH_RE = re.compile(
    rf"(?<![a-zA-Z0-9_.*:/])"
    rf"("
    rf"~/{_PATH_SEGMENT}(?:/{_PATH_SEGMENT})*"
    rf"|\.\.?/{_PATH_SEGMENT}(?:/{_PATH_SEGMENT})*"
    rf"|/{_PATH_SEGMENT}(?:/{_PATH_SEGMENT})+"
    rf"|(?![itdr]/[a-f0-9]{{8}})[a-zA-Z0-9_][a-zA-Z0-9_.-]*(?:/{_PATH_SEGMENT})+"
    rf")"
    rf"(?![a-zA-Z0-9_])"
)
_SYSTEM_PATTERNS = [
    re.compile(r"^(tribunal|review|complete|validated|CI green)", re.IGNORECASE),
    re.compile(r"^\[?(sleep|daemon|system|sync)\]?", re.IGNORECASE),
    re.compile(r"^~.*~$"),
]


MENTION_COLORS: dict[str, str] = {}


def _mention_color(name: str) -> str:
    if not MENTION_COLORS:
        MENTION_COLORS.update(
            {
                "daemon": "coral",
                "swarm": "purple",
                "human": "teal",
                "tyson": "teal",
            }
        )
    attr = MENTION_COLORS.get(name.lower(), "lavender")
    return getattr(_active, attr, _active.lavender)


def mention(name: str) -> str:
    return f"{_active.bold}{_mention_color(name)}@{name}{_active.bold_off}{_active.reset}"


_AGENT_COLORS: list[int] = [
    139,
    146,
    152,
    153,
    174,
    175,
    176,
    180,
    181,
    182,
    183,
    186,
    187,
    188,
    216,
    217,
    218,
    219,
    223,
    224,
]


def agent_color(identity: str) -> str:
    lower = identity.lower()
    if lower in ("human", "tyson"):
        return _active.teal
    idx = hash(lower) % len(_AGENT_COLORS)
    return f"\033[38;5;{_AGENT_COLORS[idx]}m"


def _prim_color(prefix: str) -> str:
    return {
        "i": _active.cyan,
        "t": _active.magenta,
        "d": _active.yellow,
        "r": _active.gray,
    }.get(prefix, _active.white)


def is_system_message(text: str) -> bool:
    return any(p.search(text) for p in _SYSTEM_PATTERNS)


_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")
_EMOJI_RE = re.compile(r"[✅🔲⬜]")


def highlight_primitives(text: str, base_color: str | None = None) -> str:
    base = base_color or _active.gray

    def _color_prim(m: re.Match[str]) -> str:
        prefix, short_id = m.group(1), m.group(2)
        if prefix == "r":
            return f"{_prim_color(prefix)}{prefix}/{short_id}{base}"
        return f"{_active.bold}{_prim_color(prefix)}{prefix}/{short_id}{_active.bold_off}{base}"

    def _color_mention(m: re.Match[str]) -> str:
        return f"{_active.bold}{_mention_color(m.group(1))}@{m.group(1)}{_active.bold_off}{base}"

    def _color_bold(m: re.Match[str]) -> str:
        return f"{_active.bold}{_active.white}{m.group(1)}{_active.bold_off}{base}"

    def _color_code(m: re.Match[str]) -> str:
        return f"{_active.cyan}{m.group(1)}{base}"

    def _color_path(m: re.Match[str]) -> str:
        return f"{_active.blue}{m.group(1)}{base}"

    text = _PATH_RE.sub(_color_path, text)
    text = _PRIMITIVE_RE.sub(_color_prim, text)
    text = _MENTION_RE.sub(_color_mention, text)
    text = _BOLD_RE.sub(_color_bold, text)
    text = _CODE_RE.sub(_color_code, text)
    return _EMOJI_RE.sub("", text)


def highlight_references(text: str, base_color: str | None = None) -> str:
    base = base_color or _active.reset

    def _color_ref(m: re.Match[str]) -> str:
        prefix, short_id = m.group(1), m.group(2)
        if prefix == "r":
            return f"{_prim_color(prefix)}{prefix}/{short_id}{base}"
        return f"{_active.bold}{_prim_color(prefix)}{prefix}/{short_id}{_active.bold_off}{base}"

    return _REFERENCE_RE.sub(_color_ref, text)


def highlight_path(text: str, base_color: str | None = None) -> str:
    base = base_color or _active.reset

    def _color_path(m: re.Match[str]) -> str:
        return f"{_active.blue}{m.group(1)}{base}"

    result = _PATH_RE.sub(_color_path, text)
    if base_color:
        return f"{base_color}{result}"
    return result


def pct_color(pct: float) -> str:
    if pct >= 70:
        return _active.lime
    if pct >= 40:
        return _active.gold
    if pct >= 20:
        return _active.orange
    return _active.red


def highlight_identities(text: str, identities: set[str]) -> str:
    if not identities:
        return text
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(i) for i in sorted(identities, key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )

    def _repl(m: re.Match[str]) -> str:
        name = m.group(1)
        color = agent_color(name)
        return f"{_active.bold}{color}{name}{_active.bold_off}{_active.reset}"

    return pattern.sub(_repl, text)


ARC_FRAMES = ("◜", "◠", "◝", "◞", "◡", "◟")
BREATH_FRAMES = ("◦", "○", "◎", "●", "◉", "●", "◎", "○")
BRAILLE_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

SPINNER_STYLES = {
    "arc": ARC_FRAMES,
    "breath": BREATH_FRAMES,
    "braille": BRAILLE_FRAMES,
}


def spinner(frame: int, style: str = "arc") -> str:
    frames = SPINNER_STYLES.get(style, ARC_FRAMES)
    return frames[frame % len(frames)]
