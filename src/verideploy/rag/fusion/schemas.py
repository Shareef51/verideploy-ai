from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from verideploy.rag.retrieval.schemas import HybridRetrievalResult
from verideploy.rag.visual_retrieval.schemas import VisualSearchResult


class EvidenceChannel(StrEnum):
    TEXT = "text"
    VISUAL = "visual"
    RUNTIME = "runtime"


class RuntimeEvidenceKind(StrEnum):
    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    EVENT = "event"


class EvidenceLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID | None = None
    chunk_id: UUID | None = None
    page_id: UUID | None = None
    page_number: int | None = Field(default=None, ge=1)
    timestamp: datetime | None = None
    timecode_seconds: float | None = Field(default=None, ge=0)
    image_ref: str | None = None
    source_uri: str | None = None


class RuntimeEvidenceInput(BaseModel):
    """Normalized runtime signal input for fusion.

    This model accepts runtime evidence produced by authorized upstream adapters. It does
    not query Prometheus/log/trace systems itself; that belongs to the runtime evidence agent.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    kind: RuntimeEvidenceKind
    source_system: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50_000)
    relevance_score: float = Field(ge=0.0, le=1.0)
    source_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    observed_at: datetime
    service: str | None = None
    environment: str | None = None

    @model_validator(mode="after")
    def timestamp_must_be_aware(self) -> RuntimeEvidenceInput:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return self


class NormalizedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    tenant_id: UUID
    channel: EvidenceChannel
    source_system: str
    source_id: str
    source_key: str
    title: str
    content: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    relevance_score: float = Field(ge=0.0, le=1.0)
    source_confidence: float = Field(ge=0.0, le=1.0)
    fusion_score: float = Field(ge=0.0, le=1.0)
    locator: EvidenceLocator
    estimated_tokens: int = Field(ge=0)
    image_cost: int = Field(default=0, ge=0, le=1)
    provenance: dict[str, Any] = Field(default_factory=dict)


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(pattern=r"^VD-EVID-[A-F0-9]{12}$")
    evidence_id: UUID
    channel: EvidenceChannel
    title: str
    locator: EvidenceLocator


class ContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str
    channel: EvidenceChannel
    title: str
    content: str
    estimated_tokens: int = Field(ge=0)
    image_ref: str | None = None


class FusionBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_context_tokens: int = Field(default=8_000, ge=256, le=200_000)
    max_images: int = Field(default=4, ge=0, le=50)
    max_total_evidence: int = Field(default=20, ge=1, le=200)
    max_per_channel: int = Field(default=8, ge=1, le=100)


class MultimodalFusionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    query: str = Field(min_length=1, max_length=4_000)
    text_result: HybridRetrievalResult | None = None
    visual_result: VisualSearchResult | None = None
    visual_tenant_id: UUID | None = None
    runtime_evidence: list[RuntimeEvidenceInput] = Field(default_factory=list)
    budgets: FusionBudgets | None = None

    @model_validator(mode="after")
    def runtime_tenants_match(self) -> MultimodalFusionRequest:
        mismatches = [item.evidence_id for item in self.runtime_evidence if item.tenant_id != self.tenant_id]
        if mismatches:
            raise ValueError("runtime evidence tenant must match fusion request tenant")
        if self.text_result is not None and self.text_result.trace.tenant_id != self.tenant_id:
            raise ValueError("text retrieval tenant must match fusion request tenant")
        if self.visual_result is not None:
            if self.visual_tenant_id is None:
                raise ValueError("visual_tenant_id is required when visual_result is provided")
            if self.visual_tenant_id != self.tenant_id:
                raise ValueError("visual retrieval tenant must match fusion request tenant")
        elif self.visual_tenant_id is not None:
            raise ValueError("visual_tenant_id requires visual_result")
        return self



class CitedStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20_000)
    citation_ids: list[str] = Field(min_length=1)


class CitedMultimodalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=50_000)
    statements: list[CitedStatement] = Field(min_length=1)


class FusionTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    query: str
    candidates_by_channel: dict[EvidenceChannel, int]
    selected_by_channel: dict[EvidenceChannel, int]
    duplicate_count: int = Field(ge=0)
    dropped_for_token_budget: int = Field(ge=0)
    dropped_for_image_budget: int = Field(ge=0)
    token_budget: int
    tokens_used: int
    image_budget: int
    images_used: int
    selected_evidence_ids: list[UUID]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MultimodalFusionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: list[NormalizedEvidence]
    context: list[ContextBlock]
    citations: list[EvidenceCitation]
    contributing_channels: list[EvidenceChannel]
    trace: FusionTrace

    @model_validator(mode="after")
    def citation_closure(self) -> MultimodalFusionResult:
        evidence_ids = {item.evidence_id for item in self.evidence}
        citation_evidence = {item.evidence_id for item in self.citations}
        context_citations = {item.citation_id for item in self.context}
        known_citations = {item.citation_id for item in self.citations}
        if evidence_ids != citation_evidence:
            raise ValueError("every selected evidence item must have exactly one citation")
        if context_citations != known_citations:
            raise ValueError("context blocks and citations must have one-to-one closure")
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("duplicate evidence IDs are not allowed")
        return self


def make_citation_id(evidence_id: UUID) -> str:
    token = sha256(str(evidence_id).encode("utf-8")).hexdigest()[:12].upper()
    return f"VD-EVID-{token}"
