
import argparse
import re
from pathlib import Path

from space.lib.commands import echo, fail, space_cmd

SKILLS_DIR = Path(__file__).parent.parent / "ctx" / "skills"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DESCRIPTION_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE)


def _skill_names() -> list[str]:
    if not SKILLS_DIR.exists():
        return []
    return sorted(p.stem for p in SKILLS_DIR.glob("*.md"))


def _list_skills() -> None:
    for path in sorted(SKILLS_DIR.glob("*.md")):
        content = path.read_text()
        desc = None
        if (m := FRONTMATTER_RE.match(content)) and (d := DESCRIPTION_RE.search(m.group(1))):
            desc = d.group(1).strip()
        echo(f"  {path.stem}: {desc}" if desc else f"  {path.stem}")


@space_cmd("skill")
def main() -> None:
    parser = argparse.ArgumentParser(description="reference material for tasks")
    parser.add_argument("name", nargs="?", help="skill name")
    args = parser.parse_args()

    if args.name is None:
        _list_skills()
    elif args.name in _skill_names():
        echo((SKILLS_DIR / f"{args.name}.md").read_text().rstrip())
    else:
        fail(f"Unknown skill: {args.name}\nAvailable: {', '.join(_skill_names())}")


if __name__ == "__main__":
    main()
