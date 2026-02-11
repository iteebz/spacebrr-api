import argparse
import json
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from space.core.errors import NotFoundError
from space.core.types import ProjectId
from space.ledger import projects
from space.lib import paths, providers, tools
from space.lib.commands import echo, space_cmd
from space.lib.providers import models

EXPLORE_MODEL = models.resolve("haiku")
EXPLORE_TOOLS: set[tools.Tool] = {
    tools.Tool.SHELL,
    tools.Tool.READ,
    tools.Tool.LS,
    tools.Tool.GLOB,
    tools.Tool.GREP,
}
EXPLORE_TIMEOUT = 120


def _build_system_prompt() -> str:
    return """Fast reconnaissance. Answer the question with cited facts.

**Your job:**
- Find what they asked for
- Show where it is (file:line, refs, commits)
- Reveal patterns if they exist
- Point to what's missing or worth checking next

**You have:**
Code: ls, glob, grep, rg, read
Ledger: search, task/insight/decision/spawn list
History: git log (--grep, --oneline, -- <path>)

**Approach:**
1. Understand the question (location? pattern? prior art? impact?)
2. Search wide first (glob, ls), then narrow (grep, read)
3. Query ledger for decisions/insights/tasks when relevant
4. Check git history for "how we solved X" questions
5. Cite everything: file:line for code, refs for ledger, commits for history
6. Stop when answered

**Output:** Structured findings block with citations. Add context only if it clarifies."""


def _log_session(question: str, result: str, duration_ms: int, caller_spawn_id: str | None) -> None:
    sessions_file = paths.dot_space() / "explorer" / "sessions.jsonl"
    sessions_file.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "caller_spawn_id": caller_spawn_id,
        "question": question,
        "result": result,
        "duration_ms": duration_ms,
    }

    with sessions_file.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _run_explore(question: str, cwd: str, timeout: int = EXPLORE_TIMEOUT) -> str:
    start_time = time.monotonic()
    caller_spawn_id = paths.spawn_id()

    args = ["claude", "--print", "--output-format", "text", "--verbose"]
    args += providers.claude.task_launch_args(EXPLORE_TOOLS)
    args += ["--model", EXPLORE_MODEL]
    args += ["--add-dir", cwd]

    system_prompt = _build_system_prompt()
    args += ["-p", system_prompt]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(question)
        stdin_file = Path(f.name)

    env = {**os.environ}

    try:
        with stdin_file.open() as stdin_handle:
            result = subprocess.run(
                args,
                stdin=stdin_handle,
                capture_output=True,
                text=True,
                cwd=cwd,
                env=env,
                timeout=timeout,
            )

        duration_ms = int((time.monotonic() - start_time) * 1000)
        output_result = (
            result.stdout.strip()
            if result.returncode == 0
            else f"explore failed: {result.stderr.strip()[:200]}"
        )

        _log_session(question, output_result, duration_ms, caller_spawn_id)
        return output_result

    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        timeout_result = "explore timed out"
        _log_session(question, timeout_result, duration_ms, caller_spawn_id)
        return timeout_result
    finally:
        stdin_file.unlink(missing_ok=True)


@space_cmd("explore")
def main() -> None:
    parser = argparse.ArgumentParser(description="blocking haiku reconnaissance")
    parser.add_argument("question", help="what to explore")
    parser.add_argument(
        "-t", "--timeout", type=int, default=EXPLORE_TIMEOUT, help="timeout seconds"
    )
    parser.add_argument("-j", "--json", action="store_true", help="output in JSON format")
    parser.add_argument("-p", "--project", help="project name")
    parser.add_argument(
        "-g", "--global", dest="all_projects", action="store_true", help="all projects"
    )
    args = parser.parse_args()

    project = None
    if args.project:
        try:
            project_id = projects.get_scope(args.project)
            project = projects.get(ProjectId(project_id))
        except NotFoundError:
            pass

    cwd = project.repo_path if project and project.repo_path else str(Path.cwd())
    result = _run_explore(args.question, cwd, timeout=args.timeout)

    if args.json:
        echo(json.dumps({"question": args.question, "result": result}, indent=2))
    else:
        echo(result)
