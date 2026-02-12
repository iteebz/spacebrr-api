
from dataclasses import dataclass
from typing import Literal

from space.lib import store

Primitive = Literal["decision", "insight", "task", "reply", "spawn"]
Action = Literal[
    "created",
    "archived",
    "linked",
    "claimed",
    "released",
    "completed",
    "cancelled",
    "resolved",
    "rejected",
    "started",
    "failed",
]


@dataclass
class Activity:
    id: int
    agent_id: str
    spawn_id: str | None
    primitive: Primitive
    primitive_id: str
    action: Action
    field: str | None
    before: str | None
    after: str | None
    created_at: str


def fetch(
    primitive: Primitive | None = None,
    primitive_id: str | None = None,
    agent_id: str | None = None,
    action: Action | None = None,
    since: str | None = None,
    limit: int = 100,
) -> list[Activity]:
    with store.ensure() as conn:
        query = "SELECT * FROM activity WHERE 1=1"
        params: list[str | int] = []

        if primitive:
            query += " AND primitive = ?"
            params.append(primitive)

        if primitive_id:
            query += " AND primitive_id = ?"
            params.append(primitive_id)

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        if action:
            query += " AND action = ?"
            params.append(action)

        if since:
            query += " AND created_at > ?"
            normalized = since.replace("T", " ").split("+")[0].split("Z")[0]
            params.append(normalized)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [store.from_row(row, Activity) for row in rows]


def for_primitive(primitive_id: str) -> list[Activity]:
    return fetch(primitive_id=primitive_id)


def recent(limit: int = 50) -> list[Activity]:
    return fetch(limit=limit)
