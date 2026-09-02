from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RetrievalChannel(StrEnum):
    KEYWORD = "keyword"
    DENSE = "dense"
    HYBRID = "hybrid"


class RetrievalDocumentKind(StrEnum):
    HISTORICAL_INCIDENT = "historical_incident"
    RUNBOOK = "runbook"
    ARCHITECTURE = "architecture"
    GENERAL = "general"


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    text: str = Field(min_length=1, max_length=4_000)
    top_k: int = Field(default=10, ge=1, le=100)
    candidate_k: int = Field(default=30, ge=1, le=200)
    model_name: str
    dimensions: int = Field(gt=0)
    service: str | None = None
    environment: str | None = None
    document_kinds: list[RetrievalDocumentKind] = Field(default_factory=list, max_length=4)
    metadata_filters: "RequestedMetadataFilters | None" = None
    keyword_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    dense_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    rrf_k: int = Field(default=60, ge=1, le=200)

    @model_validator(mode="after")
    def candidate_limit_covers_output(self) -> RetrievalQuery:
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        if abs(self.keyword_weight + self.dense_weight - 1.0) > 1e-6:
            raise ValueError("retrieval channel weights must sum to 1")
        return self


class ChannelCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    document_id: UUID
    source_key: str
    title: str
    content: str
    channel: RetrievalChannel
    rank: int = Field(ge=1)
    raw_score: float
    normalized_score: float = Field(ge=0.0, le=1.0)
    document_kind: RetrievalDocumentKind = RetrievalDocumentKind.GENERAL


class RankingContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: RetrievalChannel
    rank: int = Field(ge=1)
    raw_score: float
    normalized_score: float = Field(ge=0.0, le=1.0)
    rrf_contribution: float = Field(gt=0.0)


class HybridHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    document_id: UUID
    source_key: str
    title: str
    content: str
    rank: int = Field(ge=1)
    fused_score: float = Field(gt=0.0)
    contributions: list[RankingContribution] = Field(min_length=1)
    document_kind: RetrievalDocumentKind = RetrievalDocumentKind.GENERAL


class RetrievalTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    query_text: str
    keyword_candidates: int = Field(ge=0)
    dense_candidates: int = Field(ge=0)
    rrf_k: int = Field(gt=0)
    source_diversity_limit: int = Field(gt=0)
    selected_chunk_ids: list[UUID]
    ranking: list[dict[str, Any]]
    scope_fingerprint: str | None = None
    effective_filters: dict[str, Any] = Field(default_factory=dict)
    cache_hit: bool = False


class HybridRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hits: list[HybridHit]
    trace: RetrievalTrace

from verideploy.rag.access.schemas import RequestedMetadataFilters
RetrievalQuery.model_rebuild()
