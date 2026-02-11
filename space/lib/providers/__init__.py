from types import ModuleType

from space.core.errors import NotFoundError

from . import claude, codex, gemini, models, router
from .models import ALIASES, MODELS, display, map, resolve
from .models import is_valid as is_valid_model
from .types import Provider, ProviderEvent, ProviderName, UsageStats

PROVIDERS: dict[ProviderName, ModuleType] = {
    "claude": claude,
    "codex": codex,
    "gemini": gemini,
}
PROVIDER_NAMES: tuple[ProviderName, ...] = tuple(PROVIDERS.keys())

__all__ = [
    "ALIASES",
    "MODELS",
    "PROVIDERS",
    "PROVIDER_NAMES",
    "Provider",
    "ProviderEvent",
    "UsageStats",
    "claude",
    "codex",
    "display",
    "gemini",
    "get_provider",
    "is_valid_model",
    "map",
    "models",
    "resolve",
    "router",
]


def get_provider(name: ProviderName) -> ModuleType:
    provider = PROVIDERS.get(name)
    if provider is None:
        raise NotFoundError(f"Unknown provider: {name}") from None
    return provider
