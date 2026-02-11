import re
from pathlib import Path

from space.core.errors import ValidationError
from space.core.models import Agent
from space.ledger import projects
from space.stats.swarm import swarm_age

_CTX_DIR = Path(__file__).parent
_IDENTITIES_DIR = _CTX_DIR / "identities"
_SKILLS_DIR = _CTX_DIR / "skills"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_DESCRIPTION_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE)


def _read_ctx(name: str) -> str:
    return (_CTX_DIR / name).read_text().strip()


def _identity_path(name: str) -> Path:
    if name.startswith("/") or ".." in name or not name:
        raise ValidationError(f"Invalid identity name: {name}")
    if name.endswith(".md"):
        return _IDENTITIES_DIR / name
    return _IDENTITIES_DIR / f"{name}.md"


def build(agent: Agent, cwd: Path | None = None) -> str:
    parts = []

    search_dir = cwd or Path.cwd()
    lattice = Path.home() / "space"

    arch_path = search_dir / "ARCH.md"
    if not arch_path.exists():
        arch_path = lattice / "ARCH.md"

    space_path = search_dir / "SPACE.md"
    if not space_path.exists():
        space_path = lattice / "SPACE.md"

    if agent.identity:
        identity_path = _identity_path(agent.identity)
        identity_content = identity_path.read_text().strip()
        parts.append(f"<identity>\n{identity_content}\n</identity>")

    welcome_text = _read_ctx("welcome.md")
    age = swarm_age()
    welcome_text = welcome_text.replace("{swarm_age}", str(age))
    parts.append(f"<welcome>\n{welcome_text}\n</welcome>")

    constitution = _constitution_for_cwd(cwd)
    parts.append(f"<constitution>\n{constitution}\n</constitution>")

    if space_path.exists():
        parts.append(f"<steering>\n{space_path.read_text().strip()}\n</steering>")

    if arch_path.exists():
        parts.append(f"<architecture>\n{arch_path.read_text().strip()}\n</architecture>")

    skill_index = _skill_index()
    if skill_index:
        parts.append(f"<skills>\n{skill_index}\n</skills>")

    return "\n\n".join(parts)


def _constitution_for_cwd(cwd: Path | None) -> str:
    if cwd:
        try:
            project = projects.find_by_path(cwd.resolve())
            if project and project.type == "customer":
                return _read_ctx("constitution_customer.md")
        except Exception:  # noqa: S110
            pass
    return _read_ctx("constitution.md")


def _skill_index() -> str:
    if not _SKILLS_DIR.exists():
        return ""
    lines = []
    for path in sorted(_SKILLS_DIR.glob("*.md")):
        content = path.read_text()
        desc = path.stem
        if (m := _FRONTMATTER_RE.match(content)) and (d := _DESCRIPTION_RE.search(m.group(1))):
            desc = f"{path.stem}: {d.group(1).strip()}"
        lines.append(f"  {desc}")
    if not lines:
        return ""
    return "Available skills (-s flag on @ and spawn):\n" + "\n".join(lines)
