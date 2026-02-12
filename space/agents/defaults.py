
from space import agents, ctx
from space.core.errors import ConflictError
from space.core.models import Agent
from space.lib import store
from space.lib.providers import models

DEFAULT_MODEL = models.resolve("opus")
SYSTEM_IDENTITY = "system"


def available_identities() -> list[str]:
    return sorted(p.stem for p in ctx.IDENTITIES_DIR.glob("*.md"))


def ensure_agent(handle: str) -> bool:
    identity_file = ctx.IDENTITIES_DIR / f"{handle}.md"
    if not identity_file.exists():
        return False

    existing = _get_by_handle_any(handle)
    if existing:
        if existing.archived_at:
            agents.unarchive(existing.id)
            return True
        return False

    agents.create(
        handle=handle,
        model=DEFAULT_MODEL,
        identity=f"{handle}.md",
    )
    return True


def _get_by_handle_any(handle: str) -> Agent | None:
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE handle = ? AND merged_into IS NULL LIMIT 1",
            (handle,),
        ).fetchone()
        return store.from_row(row, Agent) if row else None


def ensure_system() -> Agent:
    with store.ensure() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE handle = ? LIMIT 1",
            (SYSTEM_IDENTITY,),
        ).fetchone()
        if row:
            return store.from_row(row, Agent)

    try:
        return agents.create(handle=SYSTEM_IDENTITY, type="system")
    except ConflictError:
        with store.ensure() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE handle = ? LIMIT 1",
                (SYSTEM_IDENTITY,),
            ).fetchone()
            if not row:
                raise
            return store.from_row(row, Agent)


def ensure() -> tuple[list[str], list[str]]:
    registered = []
    skipped = []

    for handle in available_identities():
        if ensure_agent(handle):
            registered.append(handle)
        else:
            skipped.append(handle)

    return registered, skipped
