from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApprovalRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class ApprovalEventType(StrEnum):
    CREATED = "created"
    CLAIMED = "claimed"
    DELEGATED = "delegated"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    RESUMED = "resumed"


TERMINAL_STATUSES = frozenset({ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED, ApprovalStatus.CANCELLED})
ACTIVE_STATUSES = frozenset({ApprovalStatus.PENDING, ApprovalStatus.IN_REVIEW, ApprovalStatus.CHANGES_REQUESTED})


class EvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=10_000)
    evidence_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    risk_factors: tuple[str, ...] = ()


class ReviewPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str = Field(min_length=1, max_length=120)
    min_risk_score: int = Field(default=80, ge=0, le=100)
    required_roles: tuple[str, ...] = ("release_reviewer",)
    expiry_seconds: int = Field(default=3600, ge=60, le=604800)
    allow_delegation: bool = True
    require_comment_on_reject: bool = True

    def requires_review(self, *, risk_score: int, risk: ApprovalRisk) -> bool:
        return risk in {ApprovalRisk.HIGH, ApprovalRisk.CRITICAL} or risk_score >= self.min_risk_score


class ApprovalRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    run_id: UUID
    investigation_id: str = Field(min_length=1, max_length=255)
    action_type: str = Field(min_length=1, max_length=160)
    action_payload: dict[str, Any] = Field(default_factory=dict)
    risk: ApprovalRisk
    risk_score: int = Field(ge=0, le=100)
    requested_by: str = Field(min_length=1, max_length=256)
    evidence_summary: EvidenceSummary
    policy: ReviewPolicy
    idempotency_key: str = Field(min_length=8, max_length=255)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    run_id: UUID
    investigation_id: str
    action_type: str
    action_payload: dict[str, Any]
    risk: ApprovalRisk
    risk_score: int
    requested_by: str
    evidence_summary: EvidenceSummary
    policy: ReviewPolicy
    idempotency_key: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    reviewer_id: str | None = None
    delegated_to: str | None = None
    decision_comment: str | None = None
    version: int = Field(default=1, ge=1)
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def aware_times(self) -> "ApprovalRequest":
        for value in (self.expires_at, self.created_at, self.updated_at):
            if value.tzinfo is None:
                raise ValueError("approval timestamps must be timezone-aware")
        return self


class ApprovalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID = Field(default_factory=uuid4)
    approval_id: UUID
    tenant_id: UUID
    sequence: int = Field(ge=1)
    event_type: ApprovalEventType
    actor_id: str
    actor_role: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    previous_status: ApprovalStatus | None = None
    new_status: ApprovalStatus | None = None
    signed_payload_sha256: str = Field(min_length=64, max_length=64)
    signature: str = Field(min_length=64, max_length=64)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewerContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_id: str = Field(min_length=1, max_length=256)
    roles: frozenset[str] = frozenset()


class DecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    approval_id: UUID
    reviewer: ReviewerContext
    decision: ApprovalDecision
    comment: str | None = Field(default=None, max_length=4000)
    expected_version: int = Field(ge=1)


class DelegationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    approval_id: UUID
    reviewer: ReviewerContext
    delegated_to: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=1)


class ApprovalAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: UUID
    authorized: bool
    reason: str
    version: int
