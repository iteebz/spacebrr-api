#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "space" / "space-os"))

from space import agents
from space.agents.spawn import launch
from space.ctx import templates
from space.ledger import projects

def write_space_md(repo_path: Path, template: str = "testing") -> None:
    if not templates.template_exists(template):
        raise ValueError(f"Template '{template}' not found")
    
    space_md = repo_path / "SPACE.md"
    if space_md.exists():
        return
    
    space_md.write_text(templates.get_template(template))

def main():
    if len(sys.argv) < 3:
        print("usage: provision.py <name> <repo_path> [template]", file=sys.stderr)
        sys.exit(1)
    
    name = sys.argv[1]
    repo_path = Path(sys.argv[2])
    template = sys.argv[3] if len(sys.argv) > 3 else "testing"
    
    project = projects.create(name, str(repo_path))
    write_space_md(repo_path, template)
    
    scout = agents.get_by_handle("scout")
    launch.launch(scout.id, cwd=str(repo_path))
    
    print(project.id)

if __name__ == "__main__":
    main()
