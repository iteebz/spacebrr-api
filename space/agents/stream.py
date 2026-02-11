import argparse
import subprocess
import sys

from space import agents
from space.agents import identity
from space.core.types import ProjectId
from space.ledger import insights, projects
from space.lib import store
from space.lib.commands import echo, fail, space_cmd


@space_cmd("stream")
def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        parser = argparse.ArgumentParser(description="capture human consciousness")
        parser.add_argument("content", nargs="?", help="stream content")
        parser.add_argument("-p", "--project", help="project name")

        if len(sys.argv) > 1 and sys.argv[1] == "stream":
            args = parser.parse_args(sys.argv[2:])
        else:
            args = parser.parse_args()

    content = args.content
    if content is None:
        result = subprocess.run(["vi", "-"], capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(0)
        content = result.stdout
    if not content or not content.strip():
        sys.exit(0)

    agent_id = identity.current()
    if not agent_id:
        fail("ERROR: SPACE_IDENTITY not set")

    human = agents.get_by_handle(agent_id)
    project_id = projects.get_scope(args.project)
    project = projects.get(ProjectId(project_id))

    entry = insights.create(
        project_id=project.id,
        agent_id=human.id,
        content=content.strip(),
        domain="stream",
    )
    echo(f"  {store.ref('insights', entry.id)}")
