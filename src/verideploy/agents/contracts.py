from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AGENT_CAPABILITIES={
    "github":{"purpose":"read repository and delivery metadata","permissions":["github.repository.read","github.pull_request.read","github.commit.read","github.workflow.read"]},
    "rag":{"purpose":"retrieve internal knowledge evidence","permissions":["retrieval.read"]},
    "visual_evidence":{"purpose":"retrieve and inspect visual evidence","permissions":["visual.search","visual.analyze"]},
    "runtime_evidence":{"purpose":"read metrics, logs, traces, and dashboards","permissions":["runtime.metrics.read","runtime.logs.read","runtime.traces.read","runtime.dashboards.read"]},
    "rca":{"purpose":"synthesize evidence-grounded hypotheses","permissions":["rca.analysis.read"]},
    "critic":{"purpose":"verify RCA claims and contradictions","permissions":["critic.analysis.read"]},
}


class AgentName(StrEnum):
    SUPERVISOR = "supervisor"
    PLANNING = "planning"
    GITHUB = "github"
    RAG = "rag"
    VISUAL_EVIDENCE = "visual_evidence"
    RUNTIME_EVIDENCE = "runtime_evidence"
    RCA = "rca"
    CRITIC = "critic"


class AgentRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ToolPermission(StrEnum):
    GITHUB_REPOSITORY_READ = "github.repository.read"
    GITHUB_PULL_REQUEST_READ = "github.pull_request.read"
    GITHUB_COMMIT_READ = "github.commit.read"
    GITHUB_WORKFLOW_READ = "github.workflow.read"
    RAG_RETRIEVAL_READ = "rag.retrieval.read"
    VISUAL_EVIDENCE_READ = "visual.evidence.read"
    RUNTIME_EVIDENCE_READ = "runtime.evidence.read"
    RCA_ANALYSIS_READ = "rca.analysis.read"
    CRITIC_ANALYSIS_READ = "critic.analysis.read"


class AgentAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    user_id: str = Field(min_length=1, max_length=160)
    allowed_permissions: frozenset[ToolPermission] = Field(default_factory=frozenset)

    def require(self, permissions: list[ToolPermission]) -> None:
        missing = sorted(set(permissions) - set(self.allowed_permissions))
        if missing:
            raise PermissionError("missing agent permissions: " + ", ".join(str(p) for p in missing))


class ToolBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_calls: int = Field(default=8, ge=0, le=64)
    calls_used: int = Field(default=0, ge=0, le=64)

    @model_validator(mode="after")
    def within_limit(self) -> "ToolBudget":
        if self.calls_used > self.max_calls:
            raise ValueError("tool calls used exceeds budget")
        return self

    @property
    def remaining(self) -> int:
        return self.max_calls - self.calls_used

    def consume(self, count: int = 1) -> "ToolBudget":
        if count < 1 or self.calls_used + count > self.max_calls:
            raise RuntimeError("agent tool budget exhausted")
        return self.model_copy(update={"calls_used": self.calls_used + count})


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    user_id: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=20_000)
    context: dict[str, Any] = Field(default_factory=dict)


class SupervisorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    route: Literal["planning", "github", "rag", "visual_evidence", "runtime_evidence", "rca", "critic"]
    rationale: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0, le=1)
    required_permissions: list[ToolPermission] = Field(default_factory=list, max_length=16)

    @field_validator("required_permissions", mode="before")
    @classmethod
    def decode_permissions(cls, value):
        return [ToolPermission(item) if isinstance(item, str) else item for item in (value or [])]

    @model_validator(mode="after")
    def visual_route_requires_permission(self) -> "SupervisorDecision":
        if self.route == "visual_evidence" and ToolPermission.VISUAL_EVIDENCE_READ not in self.required_permissions:
            raise ValueError("visual_evidence route requires visual.evidence.read")
        if self.route == "runtime_evidence" and ToolPermission.RUNTIME_EVIDENCE_READ not in self.required_permissions:
            raise ValueError("runtime_evidence route requires runtime.evidence.read")
        if self.route == "rca" and ToolPermission.RCA_ANALYSIS_READ not in self.required_permissions:
            raise ValueError("rca route requires rca.analysis.read")
        if self.route == "critic" and ToolPermission.CRITIC_ANALYSIS_READ not in self.required_permissions:
            raise ValueError("critic route requires critic.analysis.read")
        return self


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    step_id: str = Field(pattern=r"^step-[0-9]{2}$")
    agent: Literal["github", "rag", "visual_evidence", "runtime_evidence", "rca", "critic"]
    objective: str = Field(min_length=1, max_length=4000)
    required_permissions: list[ToolPermission] = Field(default_factory=list, max_length=16)
    max_tool_calls: int = Field(default=3, ge=0, le=16)
    depends_on: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("required_permissions", mode="before")
    @classmethod
    def decode_permissions(cls, value):
        return [ToolPermission(item) if isinstance(item, str) else item for item in (value or [])]


class AgentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_id: UUID = Field(default_factory=uuid4)
    rationale: str = Field(min_length=1, max_length=4000)
    steps: list[PlanStep] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_dag_order(self) -> "AgentPlan":
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in seen:
                raise ValueError("duplicate plan step_id")
            unknown = set(step.depends_on) - seen
            if unknown:
                raise ValueError("plan dependency must reference an earlier step")
            seen.add(step.step_id)
        return self


class GitHubToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    call_id: str = Field(pattern=r"^call-[0-9]{2}$")
    permission: ToolPermission
    operation: Literal["repository.get", "pull_request.get", "commit.get", "workflow.get"]
    arguments: dict[str, str] = Field(default_factory=dict)

    @field_validator("permission", mode="before")
    @classmethod
    def decode_permission(cls, value):
        return ToolPermission(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def permission_matches_operation(self) -> "GitHubToolCall":
        expected = {
            "repository.get": ToolPermission.GITHUB_REPOSITORY_READ,
            "pull_request.get": ToolPermission.GITHUB_PULL_REQUEST_READ,
            "commit.get": ToolPermission.GITHUB_COMMIT_READ,
            "workflow.get": ToolPermission.GITHUB_WORKFLOW_READ,
        }[self.operation]
        if self.permission != expected:
            raise ValueError("GitHub operation permission mismatch")
        return self


class GitHubToolPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    calls: list[GitHubToolCall] = Field(default_factory=list, max_length=8)
    rationale: str = Field(min_length=1, max_length=4000)


class GitHubFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    statement: str = Field(min_length=1, max_length=4000)
    source_call_ids: list[str] = Field(min_length=1, max_length=16)


class GitHubAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1, max_length=8000)
    findings: list[GitHubFinding] = Field(default_factory=list, max_length=64)
    tool_calls_used: int = Field(ge=0, le=64)


AgentOutput = Annotated[SupervisorDecision | AgentPlan | GitHubAgentResult, Field(union_mode="left_to_right")]
