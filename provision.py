#!/usr/bin/env python3
import os
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

def install_hook(repo_path: Path) -> None:
    hook_source = Path.home() / "space" / "space-os" / "scripts" / "hooks" / "commit-msg-saas"
    hook_dest = repo_path / ".git" / "hooks" / "commit-msg"
    
    if not hook_source.exists():
        print(f"WARNING: hook template not found at {hook_source}", file=sys.stderr)
        return
    
    hook_dest.parent.mkdir(parents=True, exist_ok=True)
    hook_dest.write_text(hook_source.read_text())
    hook_dest.chmod(0o755)

def main():
    if len(sys.argv) < 6:
        print("usage: provision.py <name> <repo_path> <github_login> <repo_url> <template>", file=sys.stderr)
        sys.exit(1)
    
    name = sys.argv[1]
    repo_path = Path(sys.argv[2])
    github_login = sys.argv[3]
    repo_url = sys.argv[4]
    template = sys.argv[5] if len(sys.argv) > 5 else "testing"
    
    project = projects.create_customer(
        name=name,
        repo_path=str(repo_path),
        github_login=github_login,
        repo_url=repo_url,
    )
    write_space_md(repo_path, template)
    install_hook(repo_path)
    
    scout = agents.get_by_handle("scout")
    launch.launch(scout.id, cwd=str(repo_path))
    
    print(project.id)

if __name__ == "__main__":
    main()
