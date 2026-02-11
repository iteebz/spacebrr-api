"""Skill loading and injection."""

import re
from pathlib import Path

from space.core.errors import ValidationError

_CTX_DIR = Path(__file__).parent
_SKILLS_DIR = _CTX_DIR / "skills"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def list_skills() -> list[str]:
    """List available skill names."""
    if not _SKILLS_DIR.exists():
        return []
    return sorted(p.stem for p in _SKILLS_DIR.glob("*.md"))


def load(name: str) -> str:
    """Load skill content by name.

    Strips frontmatter if present.
    """
    path = _SKILLS_DIR / f"{name}.md"
    if not path.exists():
        raise ValidationError(f"Unknown skill: {name}")

    content = path.read_text().strip()
    if match := _FRONTMATTER_RE.match(content):
        content = content[len(match.group(0)) :].strip()

    return content


def inject(names: list[str]) -> str:
    """Compose multiple skills into single context block."""
    if not names:
        return ""

    blocks = [load(name) for name in names]
    return "<skills>\n" + "\n\n---\n\n".join(blocks) + "\n</skills>"
