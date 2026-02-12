
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from space.lib import paths

_cache: "Config | None" = None
_cache_mtime: float = 0.0


@dataclass
class BackupConfig:
    spawns_per_backup: int = 5


@dataclass
class EmailConfig:
    api_key: str | None = None
    from_addr: str = "hello@spaceos.sh"


@dataclass
class SwarmConfig:
    enabled: bool = False
    limit: int | None = None
    enabled_at: str | None = None
    concurrency: int = 1
    agents: list[str] | None = None
    providers: list[str] | None = None
    weights: dict[str, float] | None = None
    capacity_threshold: float = 10.0
    project: str | None = None


@dataclass
class Config:
    swarm: SwarmConfig = field(default_factory=SwarmConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    default_identity: str | None = None
    stats_json_path: str | None = None


def _config_path() -> Path:
    return paths.dot_space() / "config.yaml"


def _from_dict(data: dict[str, Any]) -> Config:
    swarm_data = data.get("swarm", {})
    backup_data = data.get("backup", {})
    email_data = data.get("email", {})
    swarm_fields = {f.name for f in fields(SwarmConfig)}
    swarm_kwargs = {k: v for k, v in swarm_data.items() if k in swarm_fields}
    if "weights" in swarm_data and isinstance(swarm_data["weights"], dict):
        swarm_kwargs["weights"] = {str(k): float(v) for k, v in swarm_data["weights"].items()}
    return Config(
        swarm=SwarmConfig(**swarm_kwargs),
        backup=BackupConfig(
            **{k: v for k, v in backup_data.items() if k in {f.name for f in fields(BackupConfig)}}
        ),
        email=EmailConfig(
            **{k: v for k, v in email_data.items() if k in {f.name for f in fields(EmailConfig)}}
        ),
        default_identity=data.get("default_identity"),
        stats_json_path=data.get("stats_json_path"),
    )


def load() -> Config:
    global _cache, _cache_mtime
    p = _config_path()
    if not p.exists():
        return Config()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return Config()
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    data: dict[str, Any] = yaml.safe_load(p.read_text()) or {}
    _cache = _from_dict(data)
    _cache_mtime = mtime
    return _cache


def save(cfg: Config) -> None:
    global _cache, _cache_mtime
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(asdict(cfg), default_flow_style=False))
    _cache = cfg
    try:
        _cache_mtime = p.stat().st_mtime
    except OSError:
        _cache_mtime = 0.0
