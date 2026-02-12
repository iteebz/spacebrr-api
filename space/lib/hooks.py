import logging
import re
import uuid
from typing import Any, Protocol

from space.core.models import Spawn

logger = logging.getLogger(__name__)

BATCH_STATE_PREFIX = "batch_"


class SpawnHook(Protocol):
    def on_complete(self, spawn: Spawn, output: str | None) -> None: ...


_hooks: list[SpawnHook] = []


def register(hook: SpawnHook) -> None:
    _hooks.append(hook)


def run_all(spawn: Spawn, output: str | None = None) -> None:
    for hook in _hooks:
        try:
            hook.on_complete(spawn, output)
        except Exception as e:
            logger.error("Hook %s failed: %s", hook.__class__.__name__, e)


class BackupHook:
    def on_complete(self, spawn: Spawn, output: str | None) -> None:
        from space.lib import backup  # noqa: PLC0415

        backup.on_spawn_complete()


HUMAN_MENTION_PATTERN = re.compile(r"@human\b", re.IGNORECASE)
IRREVERSIBLE_PATTERN = re.compile(r"irreversible|requires.*approval|cannot.*undo", re.IGNORECASE)
ERROR_PATTERN = re.compile(r"\berror\b.*failed|\bfailed\b.*error|critical|fatal", re.IGNORECASE)


class WakeHook:
    def on_complete(self, spawn: Spawn, output: str | None) -> None:
        if not output:
            return

        reasons: list[str] = []
        if HUMAN_MENTION_PATTERN.search(output):
            reasons.append("@human mentioned")
        if IRREVERSIBLE_PATTERN.search(output):
            reasons.append("irreversible decision")
        if ERROR_PATTERN.search(output):
            reasons.append("error state")

        if not reasons:
            return

        from space.lib import devices, push  # noqa: PLC0415

        tokens = devices.get_push_tokens_for_handle("tyson")
        if tokens:
            agent_name = spawn.agent_id[:8] if spawn.agent_id else "unknown"
            push.send(
                tokens=tokens,
                title=f"Wake: {agent_name}",
                body=", ".join(reasons),
                data={"route": f"/spawns/{spawn.id}"},
            )


def create_batch(spawn_ids: list[str], notify: bool = True) -> str:
    from space.lib import state  # noqa: PLC0415

    batch_id = str(uuid.uuid4())[:8]
    batch_data: dict[str, Any] = {
        "spawn_ids": spawn_ids,
        "completed": [],
        "notify": notify,
    }
    state.set(f"{BATCH_STATE_PREFIX}{batch_id}", batch_data)
    return batch_id


def get_batch(batch_id: str) -> dict[str, Any] | None:
    from space.lib import state  # noqa: PLC0415

    return state.get(f"{BATCH_STATE_PREFIX}{batch_id}")


class BatchHook:
    def on_complete(self, spawn: Spawn, output: str | None) -> None:
        from space.lib import devices, push, state  # noqa: PLC0415

        all_state = state._load()
        for key in list(all_state.keys()):
            if not key.startswith(BATCH_STATE_PREFIX):
                continue

            batch = all_state[key]
            if spawn.id not in batch.get("spawn_ids", []):
                continue

            if spawn.id not in batch.get("completed", []):
                batch["completed"].append(spawn.id)
                state.set(key, batch)

            total = len(batch["spawn_ids"])
            done = len(batch["completed"])

            if done >= total and batch.get("notify"):
                batch_id = key.removeprefix(BATCH_STATE_PREFIX)
                tokens = devices.get_push_tokens_for_handle("tyson")
                if tokens:
                    push.send(
                        tokens=tokens,
                        title="Batch complete",
                        body=f"{batch_id}: {done}/{total} spawns",
                        data={"route": "/swarm"},
                    )
                state.delete(key)


SILENT_ERRORS = frozenset({"no summary"})


class FailureHook:
    def on_complete(self, spawn: Spawn, output: str | None) -> None:
        if not spawn.error or spawn.error in SILENT_ERRORS:
            return

        from space.lib import devices, push, store  # noqa: PLC0415

        try:
            with store.ensure() as conn:
                row = conn.execute(
                    "SELECT handle FROM agents WHERE id = ?", (spawn.agent_id,)
                ).fetchone()
            identity = row["handle"] if row else spawn.agent_id[:8]
        except Exception:
            identity = spawn.agent_id[:8]

        tokens = devices.get_push_tokens_for_handle("tyson")
        if tokens:
            push.send(
                tokens=tokens,
                title=f"Spawn failed: {identity}",
                body=spawn.error[:100],
                data={"route": f"/spawns/{spawn.id}"},
            )


register(BackupHook())
register(WakeHook())
register(BatchHook())
register(FailureHook())
