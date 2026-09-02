from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PostmortemStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    REJECTED = "REJECTED"


class ApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"


class TimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    occurred_at: datetime
    summary: Annotated[str, Field(min_length=3, max_length=1000)]
    evidence_ids: Annotated[list[str], Field(min_length=1, max_length=50)]


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: Annotated[str, Field(min_length=3, max_length=1500)]
    evidence_ids: Annotated[list[str], Field(min_length=1, max_length=50)]


class ReviewedEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed_by: UUID
    reviewed_at: datetime
    evidence_ids: Annotated[list[str], Field(min_length=1, max_length=500)]
    timeline: Annotated[list[TimelineEntry], Field(min_length=1, max_length=500)]
    root_cause: Annotated[str, Field(min_length=10, max_length=5000)]
    root_cause_category: Annotated[str, Field(min_length=2, max_length=120)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    contributing_factors: list[str] = Field(default_factory=list, max_length=100)
    impact: Annotated[str, Field(min_length=3, max_length=5000)]
    remediation_actions: Annotated[list[str], Field(min_length=1, max_length=100)]
    prevention_actions: Annotated[list[str], Field(min_length=1, max_length=100)]
    limitations: list[str] = Field(default_factory=list, max_length=100)
    citations: Annotated[list[Citation], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def validate_evidence_references(self) -> "ReviewedEvidenceBundle":
        allowed = set(self.evidence_ids)
        if len(allowed) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")
        referenced = {eid for item in self.timeline for eid in item.evidence_ids}
        referenced.update(eid for citation in self.citations for eid in citation.evidence_ids)
        unknown = sorted(referenced - allowed)
        if unknown:
            raise ValueError(f"timeline/citation references evidence outside reviewed set: {unknown[:5]}")
        return self


class CreatePostmortemCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    postmortem_id: UUID
    tenant_id: UUID
    investigation_id: UUID
    requested_by: UUID
    correlation_id: UUID = Field(default_factory=uuid4)
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
    title: Annotated[str, Field(min_length=5, max_length=250)]
    reviewed_evidence: ReviewedEvidenceBundle
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewPostmortemCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    postmortem_id: UUID
    tenant_id: UUID
    reviewer_id: UUID
    correlation_id: UUID
    decision: ApprovalDecision
    notes: Annotated[str, Field(min_length=3, max_length=4000)]
    expected_version: Annotated[int, Field(ge=1)]
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PostmortemRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    postmortem_id: UUID
    tenant_id: UUID
    investigation_id: UUID
    requested_by: UUID
    correlation_id: UUID
    idempotency_key: str
    title: str
    status: PostmortemStatus
    source_investigation_version: int
    evidence_reviewed_by: UUID
    evidence_reviewed_at: datetime
    evidence_ids: list[str]
    timeline: list[TimelineEntry]
    root_cause: str
    root_cause_category: str
    confidence: float
    contributing_factors: list[str]
    impact: str
    remediation_actions: list[str]
    prevention_actions: list[str]
    limitations: list[str]
    citations: list[Citation]
    approval_reviewed_by: UUID | None = None
    approval_reviewed_at: datetime | None = None
    approval_notes: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int = 1


class PostmortemExport(BaseModel):
    postmortem_id: UUID
    content_type: str
    filename: str
    content: str
