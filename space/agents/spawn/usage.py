import logging
from typing import Any

from space import agents
from space.core.models import Spawn
from space.lib import paths, providers

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LIMIT = 200000


def usage(spawn: Spawn) -> dict[str, Any] | None:
    agent = agents.get(spawn.agent_id)
    provider = providers.map(agent.model) if agent.model else None
    events_file = (
        paths.dot_space() / "spawns" / provider / f"{spawn.id}.jsonl" if provider else None
    )

    if events_file is None or not events_file.exists():
        old_path = paths.dot_space() / "spawns" / f"{spawn.id}.jsonl"
        if not old_path.exists():
            return None
        events_file = old_path

    try:
        if not provider:
            return None
        provider_cls = providers.get_provider(provider)
        usage_data = provider_cls.parse_usage(events_file)
    except Exception:
        logger.exception("Failed to parse usage for spawn %s provider %s", spawn.id, provider)
        return None

    if usage_data.input_tokens == 0:
        return None

    try:
        context_limit = providers.models.context_limit(usage_data.model)
    except Exception:
        logger.warning("Failed to get context limit for model %s, using default", usage_data.model)
        context_limit = DEFAULT_CONTEXT_LIMIT
    percentage = (
        min(100, (usage_data.input_tokens / context_limit) * 100) if context_limit > 0 else 0
    )

    return {
        "input_tokens": usage_data.input_tokens,
        "output_tokens": usage_data.output_tokens,
        "cache_read_tokens": usage_data.cache_read_tokens,
        "cache_creation_tokens": usage_data.cache_creation_tokens,
        "context_used": usage_data.input_tokens,
        "context_limit": context_limit,
        "percentage": round(percentage, 1),
        "model": usage_data.model,
    }
