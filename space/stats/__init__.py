from typing import Any

from . import code
from .api import (
    actionable_payload,
    colony_payload,
    health_payload,
    public_payload,
)
from .comparison import rsi_comparison
from .decision import challenge_rate as decision_challenge_rate
from .decision import flow as decision_flow
from .decision import half_life as decision_half_life
from .decision import influence as decision_influence
from .decision import precision as decision_precision
from .decision import reversal_rate as decision_reversal_rate
from .git import agent_commit_stats, code_extension, commit_stability, cross_agent_corrections
from .insight import (
    counterfactual_stats as insight_counterfactual,
)
from .insight import (
    decision_insight_reference_rate,
)
from .insight import (
    provenance_stats as insight_provenance,
)
from .insight import (
    reference_rate as insight_reference_rate,
)
from .public import get as public_stats
from .public import write as write_public_stats
from .swarm import (
    absence_metrics,
    artifacts_per_spawn,
    compounding,
    engagement,
    knowledge_decay,
    live,
    loop_frequency,
    open_questions,
    project_distribution,
    silent_agents,
    spawn_stats,
    status,
    task_sovereignty,
)
from .swarm import (
    snapshot as swarm,
)

__all__ = [
    "absence_metrics",
    "actionable_payload",
    "agent_commit_stats",
    "artifacts_per_spawn",
    "code",
    "code_extension",
    "colony_payload",
    "commit_stability",
    "compounding",
    "cross_agent_corrections",
    "decision_challenge_rate",
    "decision_flow",
    "decision_half_life",
    "decision_influence",
    "decision_insight_reference_rate",
    "decision_precision",
    "decision_reversal_rate",
    "engagement",
    "get_summary",
    "health_payload",
    "insight_counterfactual",
    "insight_provenance",
    "insight_reference_rate",
    "knowledge_decay",
    "live",
    "loop_frequency",
    "open_questions",
    "project_distribution",
    "public_payload",
    "public_stats",
    "rsi_comparison",
    "silent_agents",
    "spawn_stats",
    "status",
    "swarm",
    "task_sovereignty",
    "write_public_stats",
]


def get_summary(hours: int = 24) -> dict[str, Any]:
    """Aggregate all stats."""
    return {
        "hours": hours,
        "artifacts_per_spawn": artifacts_per_spawn(hours),
        "loop_frequency": loop_frequency(hours),
        "decision_flow": decision_flow(),
        "open_questions": open_questions(),
        "engagement": engagement(hours),
        "compounding": compounding(),
        "decision_influence": decision_influence(),
        "decision_precision": decision_precision(),
        "task_sovereignty": task_sovereignty(),
        "silent_agents": silent_agents(hours),
        "absence": absence_metrics(hours * 7),
    }
