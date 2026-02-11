from space import agents
from space.core.models import Task, TaskStatus
from space.core.types import AgentId
from space.lib import store

MAX_CONTENT_LENGTH = 70

STATUS_INDICATORS = {
    TaskStatus.PENDING: " ",
    TaskStatus.ACTIVE: "*",
    TaskStatus.DONE: "x",
    TaskStatus.CANCELLED: "-",
}


def format_task_line(task: Task, agent_map: dict[AgentId, str] | None = None) -> str:
    task_ref = store.ref("tasks", task.id)
    status_char = STATUS_INDICATORS.get(task.status, " ")
    assignee = ""
    if task.assignee_id and agent_map:
        identity = agent_map.get(task.assignee_id, task.assignee_id[:8])
        assignee = f"@{identity} "
    content = task.content[:MAX_CONTENT_LENGTH]
    if len(task.content) > MAX_CONTENT_LENGTH:
        content += "..."
    return f"[{status_char}] [{task_ref}] {assignee}{content}"


def format_task_list(task_list: list[Task], agent_id: AgentId | None = None) -> str:
    if not task_list:
        return "No tasks"

    assignee_ids = [t.assignee_id for t in task_list if t.assignee_id]
    agent_map = {}
    if assignee_ids:
        agent_objs = agents.batch_get(assignee_ids)
        agent_map = {aid: agent_objs[aid].handle for aid in agent_objs}

    if not agent_id:
        return "\n".join(format_task_line(t, agent_map) for t in task_list)

    mine = [t for t in task_list if t.assignee_id and t.assignee_id == agent_id]
    others = [t for t in task_list if not t.assignee_id or t.assignee_id != agent_id]

    lines = []
    if mine:
        lines.append("MY TASKS:")
        lines.extend(f"  {format_task_line(t, agent_map)}" for t in mine)
    if others:
        if mine:
            lines.append("")
        lines.append("OTHER TASKS:")
        lines.extend(f"  {format_task_line(t, agent_map)}" for t in others)

    return "\n".join(lines)
