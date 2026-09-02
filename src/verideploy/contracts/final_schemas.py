from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CitationReference(ContractModel):
    citation_id: Annotated[str, Field(min_length=1, max_length=160)]
    evidence_id: Annotated[str, Field(min_length=1, max_length=160)]
    source_type: Literal["document", "log", "metric", "trace", "image", "audio", "video", "code", "release"]
    locator: Annotated[str, Field(min_length=1, max_length=500)]
    claim_ids: tuple[str, ...] = ()


class EvidenceReference(ContractModel):
    evidence_id: Annotated[str, Field(min_length=1, max_length=160)]
    kind: Annotated[str, Field(min_length=1, max_length=80)]
    summary: Annotated[str, Field(min_length=1, max_length=2_000)]
    provenance_id: Annotated[str, Field(min_length=1, max_length=200)]
    citation_ids: tuple[str, ...] = ()
    observed_at: datetime | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0


class TimelineEntry(ContractModel):
    event_id: Annotated[str, Field(min_length=1, max_length=160)]
    occurred_at: datetime
    event_type: Annotated[str, Field(min_length=1, max_length=120)]
    summary: Annotated[str, Field(min_length=1, max_length=2_000)]
    evidence_ids: tuple[str, ...] = ()
    causal: bool = False


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    EXPIRED = "EXPIRED"


class ReviewResponse(ContractModel):
    review_id: UUID | None = None
    status: ReviewStatus
    required: bool
    reviewer_id: UUID | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    signature_id: str | None = None

    @model_validator(mode="after")
    def validate_required_status(self) -> "ReviewResponse":
        if self.required and self.status == ReviewStatus.NOT_REQUIRED:
            raise ValueError("required review cannot have NOT_REQUIRED status")
        return self


class RiskBand(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskDecision(StrEnum):
    PROCEED = "PROCEED"
    PROCEED_WITH_GUARDRAILS = "PROCEED_WITH_GUARDRAILS"
    DELAY = "DELAY"
    BLOCK = "BLOCK"


class ReleaseRiskFinalResponse(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    assessment_id: UUID
    tenant_id: UUID
    correlation_id: UUID
    release_id: str
    status: Literal["COMPLETED"] = "COMPLETED"
    score: Annotated[int, Field(ge=0, le=100)]
    risk_band: RiskBand
    decision: RiskDecision
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    summary: Annotated[str, Field(min_length=1, max_length=4_000)]
    risk_factors: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]
    citations: tuple[CitationReference, ...]
    review: ReviewResponse
    completed_at: datetime

    @model_validator(mode="after")
    def citations_resolve(self) -> "ReleaseRiskFinalResponse":
        evidence_ids = {item.evidence_id for item in self.evidence}
        if not self.citations:
            raise ValueError("completed risk response requires citations")
        missing = {item.evidence_id for item in self.citations} - evidence_ids
        if missing:
            raise ValueError(f"citations reference unknown evidence: {sorted(missing)}")
        return self


class RootCauseAssessment(ContractModel):
    root_cause: Annotated[str, Field(min_length=1, max_length=4_000)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    supporting_evidence_ids: tuple[str, ...]
    alternative_causes: tuple[str, ...] = ()
    uncertainty: str | None = None


class RcaFinalResponse(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    investigation_id: UUID
    tenant_id: UUID
    correlation_id: UUID
    incident_id: str | None = None
    status: Literal["COMPLETED"] = "COMPLETED"
    summary: Annotated[str, Field(min_length=1, max_length=4_000)]
    rca: RootCauseAssessment
    timeline: tuple[TimelineEntry, ...]
    evidence: tuple[EvidenceReference, ...]
    citations: tuple[CitationReference, ...]
    review: ReviewResponse
    completed_at: datetime

    @model_validator(mode="after")
    def evidence_integrity(self) -> "RcaFinalResponse":
        evidence_ids = {item.evidence_id for item in self.evidence}
        if not set(self.rca.supporting_evidence_ids).issubset(evidence_ids):
            raise ValueError("RCA supporting evidence must resolve")
        if not self.citations:
            raise ValueError("completed RCA requires citations")
        if not {item.evidence_id for item in self.citations}.issubset(evidence_ids):
            raise ValueError("RCA citations must resolve to evidence")
        return self


class ApiErrorItem(ContractModel):
    field: str | None = None
    code: str
    message: str


class ApiErrorResponse(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    error_id: UUID = Field(default_factory=uuid4)
    code: Annotated[str, Field(min_length=1, max_length=120)]
    message: Annotated[str, Field(min_length=1, max_length=1_000)]
    correlation_id: UUID
    retryable: bool = False
    retry_after_seconds: Annotated[int | None, Field(ge=0, le=86_400)] = None
    details: tuple[ApiErrorItem, ...] = ()


class FinalEventPayload(ContractModel):
    resource_type: Literal["release_risk", "incident_rca", "review", "timeline", "evidence"]
    resource_id: str
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    citation_ids: tuple[str, ...] = ()


class WebSocketEventEnvelope(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID
    event_type: str
    tenant_id: UUID
    aggregate_id: str
    correlation_id: UUID
    sequence_number: Annotated[int, Field(ge=1)]
    high_watermark: Annotated[int, Field(ge=1)]
    occurred_at: datetime
    payload: FinalEventPayload

    @model_validator(mode="after")
    def sequence_not_ahead(self) -> "WebSocketEventEnvelope":
        if self.sequence_number > self.high_watermark:
            raise ValueError("sequence_number cannot exceed high_watermark")
        return self


class KafkaEventEnvelope(ContractModel):
    schema_family: Literal["verideploy.final-event"] = "verideploy.final-event"
    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID
    event_type: str
    tenant_id: UUID
    aggregate_id: str
    ordering_key: str
    sequence_number: Annotated[int, Field(ge=1)]
    correlation_id: UUID
    producer: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    causation_id: UUID | None = None
    trace_id: str | None = None
    retry_count: Annotated[int, Field(ge=0)] = 0
    payload: FinalEventPayload
