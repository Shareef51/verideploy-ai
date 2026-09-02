from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReleaseRiskStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskDecision(StrEnum):
    PROCEED = "PROCEED"
    PROCEED_WITH_GUARDRAILS = "PROCEED_WITH_GUARDRAILS"
    DELAY = "DELAY"
    BLOCK = "BLOCK"


class ReleaseRiskPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_files: Annotated[int, Field(ge=0, le=100_000)]
    changed_services: Annotated[int, Field(ge=0, le=10_000)]
    failed_workflows: Annotated[int, Field(ge=0, le=10_000)] = 0
    database_migration_changed: bool = False
    rollback_plan_verified: bool = True
    production_incidents_last_30d: Annotated[int, Field(ge=0, le=10_000)] = 0
    high_severity_incidents_last_30d: Annotated[int, Field(ge=0, le=10_000)] = 0
    test_coverage_delta_percent: Annotated[float, Field(ge=-100.0, le=100.0)] = 0.0
    security_scan_critical_findings: Annotated[int, Field(ge=0, le=10_000)] = 0
    deployment_window_risk: Annotated[int, Field(ge=0, le=20)] = 0


class ChangedFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Annotated[str, Field(min_length=1, max_length=500)]
    additions: Annotated[int, Field(ge=0, le=1_000_000)] = 0
    deletions: Annotated[int, Field(ge=0, le=1_000_000)] = 0
    language: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    change_type: Annotated[str, Field(pattern=r"^(added|modified|deleted|renamed)$")] = "modified"

class ReleaseRiskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    tenant_id: UUID
    requested_by: UUID
    correlation_id: UUID = Field(default_factory=uuid4)
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
    repository: Annotated[str, Field(min_length=3, max_length=200)]
    release_id: Annotated[str, Field(min_length=1, max_length=120)]
    commit_sha: Annotated[str, Field(min_length=7, max_length=64, pattern=r"^[A-Fa-f0-9]+$")]
    target_environment: Annotated[str, Field(min_length=2, max_length=64)] = "production"
    policy: ReleaseRiskPolicyInput
    changed_file_details: list[ChangedFileInput] = Field(default_factory=list, max_length=10_000)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def normalize_repository(self) -> "ReleaseRiskCommand":
        self.repository = self.repository.strip()
        self.release_id = self.release_id.strip()
        self.target_environment = self.target_environment.strip().lower()
        if self.changed_file_details and len(self.changed_file_details) != self.policy.changed_files:
            raise ValueError("changed_file_details length must equal policy.changed_files")
        return self


class RiskFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    points: Annotated[int, Field(ge=0, le=100)]
    observed_value: str
    rationale: str


class ReleaseRiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    release_id: str
    score: Annotated[int, Field(ge=0, le=100)]
    level: RiskLevel
    decision: RiskDecision
    primary_risks: list[str]
    recommended_actions: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    requires_human_review: bool
    factors: list[RiskFactor]
    policy_version: str
    calculated_at: datetime


class ReleaseRiskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    tenant_id: UUID
    requested_by: UUID
    correlation_id: UUID
    idempotency_key: str
    repository: str
    release_id: str
    commit_sha: str
    target_environment: str
    status: ReleaseRiskStatus
    policy_input: ReleaseRiskPolicyInput
    changed_file_details: list[ChangedFileInput] = Field(default_factory=list)
    result: ReleaseRiskAssessment | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int = 1
