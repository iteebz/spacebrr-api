from datetime import UTC, datetime

from space.core import ids
from space.core.errors import ConflictError, NotFoundError, PermissionError, ValidationError
from space.core.models import Agent
from space.core.types import UNSET, AgentId, AgentType, Unset
from space.lib import providers, store

MIN_IDENTITY_LENGTH = 3
MAX_IDENTITY_LENGTH = 30
HUMAN_MENTION = "@human"


def validate_identity(identity: str) -> None:
    if not MIN_IDENTITY_LENGTH <= len(identity) <= MAX_IDENTITY_LENGTH:
        raise ValidationError(
            f"Identity must be between {MIN_IDENTITY_LENGTH}-{MAX_IDENTITY_LENGTH} characters"
        )
    if not identity.replace("-", "").replace("_", "").isalnum():
        raise ValidationError("Identity can only contain alphanumeric, hyphen, and underscore")


def _handle_exists(handle: str) -> bool:
    with store.ensure() as conn:
        row = conn.execute("SELECT 1 FROM agents WHERE handle = ? LIMIT 1", (handle,)).fetchone()
        return row is not None


def last_active(agent_id: AgentId) -> str | None:
    res = batch_last_active([agent_id])
    return res.get(agent_id)


def batch_last_active(agent_ids: list[AgentId]) -> dict[AgentId, str | None]:
    if not agent_ids:
        return {}
    ph = ",".join("?" * len(agent_ids))
    with store.ensure() as conn:
        rows = conn.execute(
            f"""
            SELECT id, MAX(ts) FROM (
                SELECT author_id as id, created_at as ts FROM replies WHERE author_id IN ({ph})
                UNION ALL
                SELECT agent_id as id, COALESCE(last_active_at, created_at) as ts FROM spawns WHERE agent_id IN ({ph})
                UNION ALL
                SELECT COALESCE(assignee_id, creator_id) as id, COALESCE(completed_at, started_at, created_at) as ts
                FROM tasks WHERE creator_id IN ({ph}) OR assignee_id IN ({ph})
            ) GROUP BY id
            """,  # noqa: S608
            agent_ids * 4,
        ).fetchall()
        return {AgentId(row[0]): row[1] for row in rows}


def get(agent_id: AgentId) -> Agent:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not row:
            raise NotFoundError(agent_id)
        return store.from_row(row, Agent)


def get_by_handle(handle: str) -> Agent:
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE handle = ? AND archived_at IS NULL AND merged_into IS NULL",
            (handle,),
        ).fetchone()
        if not row:
            raise NotFoundError(handle)
        return store.from_row(row, Agent)


def require_human(agent_id: AgentId, action: str = "perform this action") -> Agent:
    agent = get(agent_id)
    if agent.type != "human":
        raise PermissionError(f"only humans can {action}")
    return agent


def get_human() -> Agent | None:
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE type = 'human' AND archived_at IS NULL AND merged_into IS NULL LIMIT 1",
        ).fetchone()
        if not row:
            return None
        return store.from_row(row, Agent)


def at_human(content: str) -> bool:
    return HUMAN_MENTION in content.lower()


def batch_get(agent_ids: list[AgentId]) -> dict[AgentId, Agent]:
    if not agent_ids:
        return {}
    unique_ids = list(set(agent_ids))
    placeholders = ",".join("?" * len(unique_ids))
    with store.ensure() as conn:
        rows = conn.execute(
            f"SELECT * FROM agents WHERE id IN ({placeholders})",  # noqa: S608 - placeholders
            unique_ids,
        ).fetchall()
    return {AgentId(row["id"]): store.from_row(row, Agent) for row in rows}


def create(
    handle: str,
    type: AgentType = "ai",
    model: str | None = None,
    identity: str | None = None,
) -> Agent:
    validate_identity(handle)
    if _handle_exists(handle):
        raise ConflictError(f"Handle '{handle}' already registered")

    if type not in ("human", "ai", "system"):
        raise ValidationError(f"Invalid type '{type}'")

    if type == "ai" and not model:
        raise ValidationError("AI agents require a model")
    if type in ("human", "system") and model:
        raise ValidationError(f"{type.capitalize()} agents cannot have a model")

    if model:
        model = providers.resolve(model)
    if model and not providers.is_valid_model(model):
        raise ValidationError(f"Unknown model: {model}")

    if identity is not None and not identity.endswith(".md"):
        raise ValidationError(f"Identity must end with .md: {identity}")

    agent_id = AgentId(ids.generate("agents"))
    now_iso = datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            "INSERT INTO agents (id, handle, type, model, identity, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, handle, type, model, identity, now_iso),
        )
    return Agent(
        id=agent_id,
        handle=handle,
        type=type,
        model=model,
        identity=identity,
        avatar_path=None,
        color=None,
        created_at=now_iso,
        archived_at=None,
    )


def update(
    agent_id: AgentId,
    *,
    handle: str | Unset = UNSET,
    type: AgentType | Unset = UNSET,
    identity: str | None | Unset = UNSET,
    model: str | None | Unset = UNSET,
    avatar_path: str | None | Unset = UNSET,
    color: str | None | Unset = UNSET,
) -> Agent:
    updates: list[str] = []
    params: list[str | int | None] = []

    if handle is not UNSET:
        validate_identity(handle)
        if _handle_exists(handle):
            raise ConflictError(f"Handle '{handle}' already exists")
        updates.append("handle = ?")
        params.append(handle)
    if type is not UNSET:
        if type not in ("human", "ai", "system"):
            raise ValidationError(f"Invalid type '{type}'")
        updates.append("type = ?")
        params.append(type)
    if identity is not UNSET:
        if identity is not None and not identity.endswith(".md"):
            raise ValidationError(f"Identity must end with .md: {identity}")
        updates.append("identity = ?")
        params.append(identity)
    if model is not UNSET:
        if model is not None:
            model = providers.resolve(model)
        if model is not None and not providers.is_valid_model(model):
            raise ValidationError(f"Unknown model: {model}")
        updates.append("model = ?")
        params.append(model)
    if avatar_path is not UNSET:
        updates.append("avatar_path = ?")
        params.append(avatar_path)
    if color is not UNSET:
        updates.append("color = ?")
        params.append(color)

    if not updates:
        return get(agent_id)

    query = "UPDATE agents SET " + ", ".join(updates) + " WHERE id = ?"  # noqa: S608 - hardcoded columns
    params.append(agent_id)
    with store.write() as conn:
        conn.execute(query, params)
    return get(agent_id)


def rename(agent_id: AgentId, new_handle: str) -> Agent:
    validate_identity(new_handle)
    if _handle_exists(new_handle):
        raise ConflictError(f"Handle '{new_handle}' already exists")

    with store.write() as conn:
        conn.execute("UPDATE agents SET handle = ? WHERE id = ?", (new_handle, agent_id))
    return get(agent_id)


def archive(agent_id: AgentId) -> Agent:
    archived_at = datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            "UPDATE agents SET archived_at = ? WHERE id = ?",
            (archived_at, agent_id),
        )
    return get(agent_id)


def unarchive(agent_id: AgentId) -> Agent:
    with store.write() as conn:
        conn.execute("UPDATE agents SET archived_at = NULL WHERE id = ?", (agent_id,))
    return get(agent_id)


def fetch(
    type: AgentType | None = None,
    include_archived: bool = False,
    include_merged: bool = False,
) -> list[Agent]:
    with store.ensure() as conn:
        query = store.q("agents")
        query = query.where_if("type = ?", type)
        if not include_archived:
            query = query.not_archived()
        if not include_merged:
            query = query.where("merged_into IS NULL")
        return query.order("handle").fetch(conn, Agent)


def merge(from_id: AgentId, to_id: AgentId, human_id: AgentId) -> bool:
    require_human(human_id, "merge agents")
    if from_id == to_id:
        return False

    now_iso = datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            "UPDATE agents SET merged_into = ?, archived_at = ? WHERE id = ?",
            (to_id, now_iso, from_id),
        )

    return True
