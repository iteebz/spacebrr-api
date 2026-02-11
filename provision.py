#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from space import agents
from space.agents import spawn
from space.core.models import SpawnStatus
from space.core.types import SpawnId
from space.ctx import templates
from space.ledger import insights, projects, tasks
from space.lib import store

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

def verify_spawn(spawn_id: SpawnId, project_id: str, timeout_seconds: int = 30) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_seconds
    spawn_active = False
    
    while time.monotonic() < deadline:
        current = spawn.repo.get(spawn_id)
        if current.status == SpawnStatus.ACTIVE and current.pid:
            spawn_active = True
            break
        if current.status == SpawnStatus.DONE:
            error = current.error or "spawn completed before becoming active"
            return False, f"spawn {spawn_id[:8]} failed: {error}"
        time.sleep(0.5)
    
    if not spawn_active:
        return False, f"spawn {spawn_id[:8]} did not start within {timeout_seconds}s"
    
    ledger_deadline = time.monotonic() + 30
    while time.monotonic() < ledger_deadline:
        with store.ensure() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM insights WHERE project_id = ? AND deleted_at IS NULL",
                (project_id,),
            ).fetchone()[0]
            if count > 0:
                return True, f"spawn {spawn_id[:8]} verified"
        time.sleep(1)
    
    return False, f"spawn {spawn_id[:8]} active but no ledger writes within 30s"

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
    
    with store.ensure() as conn:
        creator_id = conn.execute("SELECT id FROM agents LIMIT 1").fetchone()[0]
    
    tasks.create(
        project_id=project.id,
        creator_id=creator_id,
        content=f"analyze {name} codebase and begin work on {template} vector",
    )
    
    try:
        scout = agents.get_by_handle("scout")
        result = spawn.launch(
            agent_id=scout.id,
            cwd=str(repo_path),
            write_starting_event=True,
        )
        
        verified, msg = verify_spawn(result.id, project.id)
        if not verified:
            print(f"ERROR: {msg}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: failed to spawn scout: {e}", file=sys.stderr)
        sys.exit(1)
    
    print(project.id)

if __name__ == "__main__":
    main()
