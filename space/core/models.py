from dataclasses import dataclass
from enum import Enum

from space.core.types import (
    AgentId,
    AgentType,
    ArtifactType,
    CliInvocationId,
    DecisionId,
    HealthMetricId,
    InsightId,
    ProjectId,
    ReplyId,
    SpawnId,
    TaskId,
)

# AGENTS


@dataclass
class Agent:
    id: AgentId
    handle: str
    type: AgentType = "ai"
    model: str | None = None
    identity: str | None = None
    avatar_path: str | None = None
    color: str | None = None
    created_at: str | None = None
    archived_at: str | None = None
    deleted_at: str | None = None
    merged_into: AgentId | None = None


@dataclass
class Project:
    id: ProjectId
    name: str
    type: str = "standard"
    repo_path: str | None = None
    github_login: str | None = None
    repo_url: str | None = None
    provisioned_at: str | None = None
    color: str | None = None
    icon: str | None = None
    tags: list[str] | None = None
    created_at: str | None = None
    archived_at: str | None = None


@dataclass
class Device:
    id: str
    owner_id: AgentId
    tailscale_ip: str
    push_token: str | None = None
    name: str | None = None
    created_at: str | None = None


# SPAWNS


class SpawnStatus(str, Enum):
    ACTIVE = "active"
    DONE = "done"


class SpawnMode(str, Enum):
    SOVEREIGN = "sovereign"
    DIRECTED = "directed"


@dataclass
class Spawn:
    id: SpawnId
    agent_id: AgentId
    caller_spawn_id: SpawnId | None = None
    status: SpawnStatus = SpawnStatus.ACTIVE
    mode: SpawnMode = SpawnMode.SOVEREIGN
    error: str | None = None
    pid: int | None = None
    session_id: str | None = None
    summary: str | None = None
    trace_hash: str | None = None
    resume_count: int = 0
    created_at: str | None = None
    last_active_at: str | None = None


# DECISIONS


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"
    COMMITTED = "committed"
    ACTIONED = "actioned"
    LEARNED = "learned"
    REJECTED = "rejected"


@dataclass
class Decision:
    id: DecisionId
    project_id: ProjectId
    agent_id: AgentId
    spawn_id: SpawnId | None = None
    content: str = ""
    rationale: str = ""
    expected_outcome: str | None = None
    reversible: bool | None = None
    outcome: str | None = None
    refs: str | None = None
    images: list[str] | None = None
    created_at: str = ""
    committed_at: str | None = None
    actioned_at: str | None = None
    rejected_at: str | None = None
    archived_at: str | None = None
    deleted_at: str | None = None


# INSIGHTS


@dataclass
class Insight:
    id: InsightId
    project_id: ProjectId
    agent_id: AgentId
    spawn_id: SpawnId | None = None
    decision_id: DecisionId | None = None
    domain: str = ""
    content: str = ""
    mentions: list[str] | None = None
    images: list[str] | None = None
    open: bool = False
    provenance: str | None = None
    counterfactual: bool | None = None
    created_at: str = ""
    archived_at: str | None = None
    deleted_at: str | None = None


# TASKS


class TaskStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: TaskId
    project_id: ProjectId
    creator_id: AgentId
    decision_id: DecisionId | None = None
    assignee_id: AgentId | None = None
    spawn_id: SpawnId | None = None
    content: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    deleted_at: str | None = None


# REPLIES


@dataclass
class Reply:
    id: ReplyId
    parent_type: ArtifactType
    parent_id: str
    author_id: AgentId
    spawn_id: SpawnId | None = None
    project_id: ProjectId | None = None
    content: str = ""
    mentions: list[str] | None = None
    images: list[str] | None = None
    created_at: str = ""
    deleted_at: str | None = None


# EMAILS


class EmailDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class EmailStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    REJECTED = "rejected"


@dataclass
class Email:
    id: str
    resend_id: str | None
    direction: EmailDirection
    from_addr: str
    to_addr: str
    subject: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    status: EmailStatus = EmailStatus.SENT
    approved_by: AgentId | None = None
    approved_at: str | None = None
    created_at: str | None = None


# HEALTH


@dataclass
class HealthMetric:
    id: HealthMetricId
    score: int
    lint_violations: int = 0
    type_errors: int = 0
    test_passed: int = 0
    test_failed: int = 0
    arch_violations: int = 0
    suppressions: int = 0
    stashes: int = 0
    project_id: ProjectId | None = None
    created_at: str = ""


# TELEMETRY


@dataclass
class CliInvocation:
    id: CliInvocationId
    ts: str
    command: str
    exit_code: int
    spawn_id: SpawnId | None = None
    args: str | None = None
    duration_ms: int | None = None
    created_at: str = ""
