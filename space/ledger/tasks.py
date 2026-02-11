from datetime import UTC, datetime

from space.core import ids
from space.core.errors import NotFoundError, StateError, ValidationError
from space.core.models import Task, TaskStatus
from space.core.types import AgentId, DecisionId, ProjectId, SpawnId, TaskId
from space.ledger import artifacts
from space.lib import store


def create(
    project_id: ProjectId,
    creator_id: AgentId,
    content: str,
    decision_id: DecisionId | None = None,
    assignee_id: AgentId | None = None,
    spawn_id: SpawnId | None = None,
    done: bool = False,
    result: str | None = None,
) -> Task:
    task_id = TaskId(ids.generate("tasks"))
    now = datetime.now(UTC).isoformat()
    status = TaskStatus.DONE if done else TaskStatus.PENDING
    assignee = creator_id if done else assignee_id
    with store.write() as conn:
        if decision_id:
            store.unarchive("decisions", decision_id, conn)
        conn.execute(
            "INSERT INTO tasks (id, project_id, creator_id, content, assignee_id, created_at, status, spawn_id, decision_id, completed_at, result) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                project_id,
                creator_id,
                content,
                assignee,
                now,
                status.value,
                spawn_id,
                decision_id,
                now if done else None,
                result,
            ),
        )
    return get(task_id)


def fetch(
    status: str | None = None,
    assignee_id: AgentId | None = None,
    creator_id: AgentId | None = None,
    spawn_ids: list[SpawnId] | None = None,
    decision_id: DecisionId | None = None,
    include_done: bool = False,
    limit: int | None = None,
    project_id: ProjectId | None = None,
    unassigned: bool = False,
) -> list[Task]:
    with store.ensure() as conn:
        query = store.q("tasks")

        if spawn_ids:
            query = query.where_in("spawn_id", spawn_ids)
            include_done = True

        if decision_id:
            query = query.where("decision_id = ?", decision_id)
            include_done = True

        if status:
            query = query.where("status = ?", status)
        elif not include_done:
            query = query.where(
                "status NOT IN (?, ?)", TaskStatus.DONE.value, TaskStatus.CANCELLED.value
            )

        query = query.where_if("assignee_id = ?", assignee_id)
        query = query.where_if("creator_id = ?", creator_id)
        query = query.where_if("project_id = ?", project_id)

        if unassigned:
            query = query.where("assignee_id IS NULL")

        return query.order("created_at DESC").limit(limit).fetch(conn, Task)


def get(task_id: TaskId) -> Task:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise NotFoundError(task_id)
        return store.from_row(row, Task)


def get_active(agent_id: AgentId) -> Task | None:
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE assignee_id = ? AND status = ?",
            (agent_id, TaskStatus.ACTIVE.value),
        ).fetchone()
        if not row:
            return None
        return store.from_row(row, Task)


VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.ACTIVE, TaskStatus.DONE, TaskStatus.CANCELLED},
    TaskStatus.ACTIVE: {TaskStatus.PENDING, TaskStatus.DONE, TaskStatus.CANCELLED},
    TaskStatus.DONE: set(),
    TaskStatus.CANCELLED: set(),
}


def set_status(
    task_id: TaskId,
    status: TaskStatus,
    agent_id: AgentId | None = None,
    result: str | None = None,
) -> Task:
    task = get(task_id)
    current = task.status
    if current == status:
        return task
    if status not in VALID_TRANSITIONS.get(current, set()):
        raise StateError(f"Cannot transition from {current.value} to {status.value}")

    now = datetime.now(UTC).isoformat()
    with store.write() as conn:
        if status == TaskStatus.ACTIVE:
            if not agent_id:
                raise ValidationError("agent_id required to claim task")
            conn.execute(
                "UPDATE tasks SET assignee_id = ?, status = ?, started_at = ? WHERE id = ?",
                (agent_id, status.value, now, task_id),
            )
        elif status == TaskStatus.PENDING and current == TaskStatus.ACTIVE:
            if not agent_id:
                raise ValidationError("agent_id required to release task")
            if task.assignee_id and task.assignee_id != agent_id:
                raise ValidationError(f"Task not claimed by agent '{agent_id}'")
            conn.execute(
                "UPDATE tasks SET assignee_id = NULL, status = ?, started_at = NULL WHERE id = ?",
                (status.value, task_id),
            )
        elif status in (TaskStatus.DONE, TaskStatus.CANCELLED):
            if (
                current == TaskStatus.ACTIVE
                and agent_id
                and task.assignee_id
                and task.assignee_id != agent_id
            ):
                raise ValidationError(f"Task not claimed by agent '{agent_id}'")
            conn.execute(
                "UPDATE tasks SET status = ?, completed_at = ?, result = ? WHERE id = ?",
                (status.value, now, result, task_id),
            )
        else:
            conn.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                (status.value, task_id),
            )
    return get(task_id)


def delete(task_id: TaskId) -> None:
    artifacts.soft_delete("tasks", task_id, "Task")


def update_content(task_id: TaskId, content: str) -> Task:
    get(task_id)
    with store.write() as conn:
        conn.execute(
            "UPDATE tasks SET content = ? WHERE id = ?",
            (content, task_id),
        )
    return get(task_id)


def switch(
    agent_id: AgentId,
    project_id: ProjectId,
    new_content: str,
    spawn_id: SpawnId | None = None,
    decision_id: DecisionId | None = None,
) -> tuple[Task | None, Task]:
    old_task = get_active(agent_id)
    if old_task:
        set_status(old_task.id, TaskStatus.DONE, agent_id=agent_id)
    new_task = create(
        project_id,
        agent_id,
        new_content,
        spawn_id=spawn_id,
        decision_id=decision_id,
        assignee_id=agent_id,
    )
    set_status(new_task.id, TaskStatus.ACTIVE, agent_id=agent_id)
    return old_task, new_task
