from pathlib import Path

from space import agents
from space.core.errors import NotFoundError, ValidationError
from space.core.models import Agent, Spawn, SpawnStatus
from space.core.types import AgentId, SpawnId
from space.ctx.prompt import resume
from space.ctx.prompt import wake as _wake
from space.ctx.system import build
from space.lib import paths, providers
from space.lib.providers import models

_CTX_DIR = Path(__file__).parent
IDENTITIES_DIR = _CTX_DIR / "identities"

PROVIDER_MAP = {
    "claude": "CLAUDE.md",
    "gemini": "GEMINI.md",
    "codex": "AGENTS.md",
}
SYSTEM_LABEL = "SYSTEM.md"

__all__ = [
    "IDENTITIES_DIR",
    "build",
    "identity_path",
    "inject",
    "resume",
    "wake",
]


def identity_path(name: str) -> Path:
    if name.startswith("/") or ".." in name or not name:
        raise ValidationError(f"Invalid identity name: {name}")
    if name.endswith(".md"):
        return IDENTITIES_DIR / name
    return IDENTITIES_DIR / f"{name}.md"


def inject(spawn: Spawn, agent: Agent, cwd: Path | None = None) -> Path:
    target_dir = paths.identity_dir(agent.handle)
    target_dir.mkdir(parents=True, exist_ok=True)

    gitconfig = target_dir / ".gitconfig"
    gitconfig.write_text(f"[user]\n\tname = {agent.handle}\n\temail = {agent.handle}@space.local\n")

    provider = providers.map(agent.model) if agent.model else "claude"
    config_file = PROVIDER_MAP.get(provider, "CLAUDE.md")
    content = build(agent, cwd)

    for stale in PROVIDER_MAP.values():
        if stale != config_file:
            (target_dir / stale).unlink(missing_ok=True)

    (target_dir / config_file).write_text(content)

    return target_dir


def _resolve_preview_agent(handle: str) -> Agent:
    try:
        return agents.repo.get_by_handle(handle)
    except NotFoundError:
        return Agent(
            id=AgentId("preview"),
            handle=handle,
            model=models.resolve("sonnet"),
            identity=f"{handle}.md" if (IDENTITIES_DIR / f"{handle}.md").exists() else None,
        )


def wake(
    spawn: Spawn | None = None, cwd: str | Path | None = None, *, identity: str | None = None
) -> str:
    if spawn is not None:
        if identity is not None:
            raise ValidationError("spawn mode cannot be combined with identity")
        return _wake(spawn)

    if not identity:
        raise ValidationError("identity is required when spawn is not provided")

    agent = _resolve_preview_agent(identity)
    cwd_path = Path(cwd) if isinstance(cwd, str) else cwd
    system_content = build(agent, cwd_path)

    fake_spawn = Spawn(
        id=SpawnId("preview-spawn"),
        agent_id=agent.id,
        status=SpawnStatus.ACTIVE,
    )
    prompt_content = _wake(fake_spawn, agent=agent)
    return f"\n=== {SYSTEM_LABEL} ===\n\n{system_content}\n\n\n=== PROMPT ===\n\n{prompt_content}"
