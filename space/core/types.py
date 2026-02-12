
from enum import Enum
from typing import Literal


class _Unset(Enum):
    UNSET = "UNSET"


UNSET: Literal[_Unset.UNSET] = _Unset.UNSET
Unset = Literal[_Unset.UNSET]

AgentType = Literal["human", "ai", "system"]


class AgentId(str):
    pass


class SpawnId(str):
    pass


class TaskId(str):
    pass


class InsightId(str):
    pass


class ProjectId(str):
    pass


class DecisionId(str):
    pass


class ReplyId(str):
    pass


class HealthMetricId(str):
    pass


class CliInvocationId(int):
    pass


ArtifactType = Literal["insight", "decision", "task"]
