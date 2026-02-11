from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from space.core.types import AgentId
from space.lib import store


@dataclass
class Device:
    id: str
    owner_id: AgentId
    tailscale_ip: str
    push_token: str | None
    name: str | None
    created_at: str


def get_by_ip(ip: str) -> Device | None:
    with store.ensure() as conn:
        row = conn.execute("SELECT * FROM devices WHERE tailscale_ip = ?", (ip,)).fetchone()
        return store.from_row(row, Device) if row else None


def register(owner_id: AgentId, tailscale_ip: str, name: str | None = None) -> Device:
    existing = get_by_ip(tailscale_ip)
    if existing:
        if existing.owner_id != owner_id:
            with store.write() as conn:
                conn.execute(
                    "UPDATE devices SET owner_id = ?, name = ? WHERE id = ?",
                    (owner_id, name or existing.name, existing.id),
                )
            return Device(
                id=existing.id,
                owner_id=owner_id,
                tailscale_ip=tailscale_ip,
                push_token=existing.push_token,
                name=name or existing.name,
                created_at=existing.created_at,
            )
        return existing

    device_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    with store.write() as conn:
        conn.execute(
            "INSERT INTO devices (id, owner_id, tailscale_ip, name, created_at) VALUES (?, ?, ?, ?, ?)",
            (device_id, owner_id, tailscale_ip, name, now_iso),
        )
    return Device(
        id=device_id,
        owner_id=owner_id,
        tailscale_ip=tailscale_ip,
        push_token=None,
        name=name,
        created_at=now_iso,
    )


def list_for_owner(owner_id: AgentId) -> list[Device]:
    with store.ensure() as conn:
        rows = conn.execute(
            "SELECT * FROM devices WHERE owner_id = ? ORDER BY created_at",
            (owner_id,),
        ).fetchall()
    return [store.from_row(row, Device) for row in rows]


def delete(device_id: str) -> bool:
    with store.write() as conn:
        cursor = conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        return cursor.rowcount > 0


def update_push_token(device_id: str, push_token: str) -> None:
    with store.write() as conn:
        conn.execute(
            "UPDATE devices SET push_token = ? WHERE id = ?",
            (push_token, device_id),
        )


def get_push_tokens_for_handle(handle: str) -> list[str]:
    with store.ensure() as conn:
        rows = conn.execute(
            """
            SELECT d.push_token FROM devices d
            JOIN agents a ON d.owner_id = a.id
            WHERE a.handle = ? AND d.push_token IS NOT NULL
            """,
            (handle,),
        ).fetchall()
    return [row["push_token"] for row in rows]
