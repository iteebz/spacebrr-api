from typing import Any

from space.core.errors import ValidationError

from .types import ProviderName

MODELS: dict[ProviderName, list[dict[str, Any]]] = {
    "claude": [
        {
            "id": "claude-haiku-4-5",
            "name": "Claude Haiku 4.5",
            "description": "Fast, lightweight",
            "context_limit": 200000,
        },
        {
            "id": "claude-sonnet-4-5",
            "name": "Claude Sonnet 4.5",
            "description": "Balanced, general purpose",
            "context_limit": 200000,
        },
        {
            "id": "claude-opus-4-5",
            "name": "Claude Opus 4.5",
            "description": "Complex reasoning",
            "context_limit": 200000,
        },
        {
            "id": "claude-opus-4-6",
            "name": "Claude Opus 4.6",
            "description": "Flagship, 1M context, agent teams",
            "context_limit": 1000000,
        },
    ],
    "codex": [
        {
            "id": "gpt-5.1",
            "name": "GPT-5.1",
            "description": "General reasoning",
            "context_limit": 272000,
        },
        {
            "id": "gpt-5.1-codex",
            "name": "GPT-5.1 Codex",
            "description": "Codex-optimized",
            "context_limit": 272000,
        },
        {
            "id": "gpt-5.1-codex-mini",
            "name": "GPT-5.1 Codex Mini",
            "description": "Cheap, fast",
            "context_limit": 272000,
        },
        {
            "id": "gpt-5.1-codex-max",
            "name": "GPT-5.1 Codex Max",
            "description": "Flagship",
            "context_limit": 272000,
        },
        {
            "id": "gpt-5.2",
            "name": "GPT-5.2",
            "description": "Latest flagship",
            "context_limit": 400000,
        },
        {
            "id": "gpt-5.2-codex",
            "name": "GPT-5.2 Codex",
            "description": "Codex-optimized",
            "context_limit": 400000,
        },
        {
            "id": "gpt-5.3-codex",
            "name": "GPT-5.3 Codex",
            "description": "Latest codex-optimized",
            "context_limit": 400000,
        },
    ],
    "gemini": [
        {
            "id": "gemini-2-5-flash-lite",
            "name": "Gemini 2.5 Flash Lite",
            "description": "Fastest, simple tasks",
            "context_limit": 1000000,
        },
        {
            "id": "gemini-2-5-flash",
            "name": "Gemini 2.5 Flash",
            "description": "Balanced, 1M context",
            "context_limit": 1000000,
        },
        {
            "id": "gemini-2-5-pro",
            "name": "Gemini 2.5 Pro",
            "description": "Stable flagship",
            "context_limit": 1000000,
        },
        {
            "id": "gemini-3-flash-preview",
            "name": "Gemini 3 Flash",
            "description": "Fast, 1M context (experimental)",
            "context_limit": 1000000,
        },
        {
            "id": "gemini-3-pro-preview",
            "name": "Gemini 3 Pro",
            "description": "Flagship (experimental)",
            "context_limit": 1000000,
        },
    ],
}

ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-5",
    "opus": "claude-opus-4-6",
    "flash": "gemini-3-flash-preview",
    "pro": "gemini-3-pro-preview",
    "codex": "gpt-5.3-codex",
    "gpt": "gpt-5.2",
}

_MODEL_INFO: dict[str, dict[str, Any]] = {
    model["id"]: model for provider_models in MODELS.values() for model in provider_models
}
_MODEL_TO_PROVIDER: dict[str, ProviderName] = {
    model["id"]: provider
    for provider, provider_models in MODELS.items()
    for model in provider_models
}


def resolve(model: str) -> str:
    return ALIASES.get(model, model)


def map(model: str) -> ProviderName:
    try:
        return _MODEL_TO_PROVIDER[resolve(model)]
    except KeyError:
        raise ValidationError(f"Unknown model: {model}") from None


def context_limit(model: str | None) -> int:
    if not model:
        return 200000
    m = resolve(model)
    return _MODEL_INFO.get(m, {}).get("context_limit", 200000)


_MODEL_TO_ALIAS: dict[str, str] = {v: k for k, v in ALIASES.items()}


def display(model: str | None) -> str:
    if not model:
        return "-"
    return _MODEL_TO_ALIAS.get(model, model)


def is_valid(model: str) -> bool:
    return resolve(model) in _MODEL_TO_PROVIDER
