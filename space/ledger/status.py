"""Actionable swarm status by project."""

from dataclasses import dataclass

from space.core.types import ProjectId
from space.ledger import decisions, inbox, insights, projects, tasks


@dataclass
class ProjectStatus:
    name: str
    project_id: ProjectId
    open_questions: int
    unclaimed_tasks: int
    committed_decisions: int
    repo_path: str | None


@dataclass
class InboxItem:
    id: str
    content: str
    author: str
    parent_type: str
    parent_id: str


@dataclass
class Status:
    projects: list[ProjectStatus]
    inbox: list[InboxItem]


def get(agent_handle: str | None = None) -> Status:
    """Get actionable status across all projects."""
    project_statuses = [
        ProjectStatus(
            name=p.name,
            project_id=p.id,
            open_questions=len(insights.fetch_open(project_id=p.id, limit=100)),
            unclaimed_tasks=len(tasks.fetch(project_id=p.id, unassigned=True, limit=100)),
            committed_decisions=len(
                decisions.fetch_by_status("committed", project_id=p.id, limit=100)
            ),
            repo_path=p.repo_path,
        )
        for p in projects.fetch()
    ]

    inbox_items = []
    if agent_handle:
        inbox_items = [
            InboxItem(
                id=i.id[:8],
                content=i.content[:100],
                author=i.author_id[:8],
                parent_type=i.parent_type if i.parent_type else i.type,
                parent_id=i.parent_id[:8] if i.parent_id else i.id[:8],
            )
            for i in inbox.fetch(agent_handle)[:10]
        ]

    return Status(projects=project_statuses, inbox=inbox_items)
