#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from space.ctx import templates
from space.ledger import projects, tasks

def write_space_md(repo_path: Path, template: str = "testing") -> None:
    if not templates.template_exists(template):
        raise ValueError(f"Template '{template}' not found")
    
    space_md = repo_path / "SPACE.md"
    if space_md.exists():
        return
    
    space_md.write_text(templates.get_template(template))

def install_hook(repo_path: Path) -> None:
    hook_source = Path(__file__).parent / "scripts" / "hooks" / "commit-msg-saas"
    hook_dest = repo_path / ".git" / "hooks" / "commit-msg"
    
    if not hook_source.exists():
        print(f"WARNING: hook template not found at {hook_source}", file=sys.stderr)
        return
    
    hook_dest.parent.mkdir(parents=True, exist_ok=True)
    hook_dest.write_text(hook_source.read_text())
    hook_dest.chmod(0o755)

def create_feature_branch(repo_path: Path) -> None:
    try:
        default_result = subprocess.run(
            ["git", "-C", str(repo_path), "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
        )
        default_branch = "main"
        if default_result.returncode == 0:
            default_branch = default_result.stdout.strip().split('/')[-1]
        
        branch_name = "space/initial-analysis"
        subprocess.run(
            ["git", "-C", str(repo_path), "checkout", "-b", branch_name, default_branch],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        pass

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
    create_feature_branch(repo_path)
    
    task = tasks.create(
        project_id=project.id,
        creator_id="system",
        content=f"analyze {name} codebase and begin work on {template} vector",
    )
    
    scout = agents.get("scout")
    launch.launch(scout.id, cwd=str(repo_path))
    
    print(project.id)

if __name__ == "__main__":
    main()
