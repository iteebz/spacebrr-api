import hashlib
from pathlib import Path

from space.core.types import SpawnId
from space.lib import store

GENESIS_HASH = "0" * 64


def compute_hash(content: str, prev_hash: str) -> str:
    data = f"{prev_hash}:{content}".encode()
    return hashlib.sha256(data).hexdigest()


def compute_chain(events_path: Path) -> str | None:
    if not events_path.exists():
        return None

    current_hash = GENESIS_HASH
    with events_path.open() as f:
        for line in f:
            line = line.rstrip("\n")
            if line:
                current_hash = compute_hash(line, current_hash)

    return current_hash


def finalize(spawn_id: SpawnId, events_path: Path) -> str | None:
    root_hash = compute_chain(events_path)
    if root_hash:
        with store.write() as conn:
            conn.execute(
                "UPDATE spawns SET trace_hash = ? WHERE id = ?",
                (root_hash, spawn_id),
            )
    return root_hash


def verify(spawn_id: SpawnId, events_path: Path) -> bool:
    with store.ensure() as conn:
        row = conn.execute("SELECT trace_hash FROM spawns WHERE id = ?", (spawn_id,)).fetchone()

    if not row or not row["trace_hash"]:
        return True

    stored_hash = row["trace_hash"]
    computed_hash = compute_chain(events_path)

    return stored_hash == computed_hash


def status(spawn_id: SpawnId, events_path: Path) -> dict[str, str | bool | None]:
    with store.ensure() as conn:
        row = conn.execute("SELECT trace_hash FROM spawns WHERE id = ?", (spawn_id,)).fetchone()

    stored = row["trace_hash"] if row else None
    computed = compute_chain(events_path)

    return {
        "stored": stored,
        "computed": computed,
        "verified": stored == computed if stored and computed else None,
        "has_trace": events_path.exists() if events_path else False,
    }
