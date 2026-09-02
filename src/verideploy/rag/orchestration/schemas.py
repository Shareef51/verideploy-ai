from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from verideploy.rag.retrieval.schemas import RetrievalChannel, RetrievalDocumentKind


class PipelineStage(StrEnum):
    ANALYZE = "analyze"
    EXPAND = "expand"
    RETRIEVE = "retrieve"
    FUSE = "fuse"
    RERANK = "rerank"
    FILTER = "filter"
    DIVERSIFY = "diversify"
    PARENT_RESOLVE = "parent_resolve"
    CONTEXT_BUILD = "context_build"


class DecisionAction(StrEnum):
    KEEP = "keep"
    DROP = "drop"
    SCORE = "score"
    SELECT = "select"


class RetrievalPipelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    query: str = Field(min_length=1, max_length=4000)
    service: str | None = None
    environment: str | None = None
    document_kinds: list[RetrievalDocumentKind] = Field(default_factory=list, max_length=4)
    metadata_filters: "RequestedMetadataFilters | None" = None
    retrieval_mode: RetrievalChannel = RetrievalChannel.HYBRID
    top_k: int = Field(default=8, ge=1, le=50)
    candidate_k: int = Field(default=30, ge=1, le=200)
    max_expansions: int = Field(default=2, ge=0, le=4)
    max_per_source: int = Field(default=2, ge=1, le=10)
    min_rerank_score: float = Field(default=0.10, ge=0.0, le=1.0)
    context_token_budget: int = Field(default=6000, ge=128, le=100000)
    model_name: str
    dimensions: int = Field(gt=0)
    query_purpose: Literal["general", "incident_rca"] = "general"
    max_subqueries: int = Field(default=6, ge=1, le=8)

    @field_validator("query", "service", "environment")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def candidate_limit_covers_output(self) -> "RetrievalPipelineRequest":
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        return self


class QueryAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    normalized_query: str
    tokens: list[str]
    expansions: list[str]
    query_version: str
    subqueries: list["QuerySubproblem"] = Field(default_factory=list)


class QuerySubproblem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subquery_id: str
    question: str
    intent: Literal["change", "telemetry", "history", "architecture", "runbook", "contradiction", "general"]
    retrieval_mode: RetrievalChannel
    candidate_k: int = Field(ge=1, le=200)
    keyword_weight: float = Field(ge=0, le=1)
    dense_weight: float = Field(ge=0, le=1)
    document_kinds: list[RetrievalDocumentKind] = Field(default_factory=list)
    metadata_first: bool = False


class ParentResolvedContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: UUID
    document_id: UUID
    source_key: str
    title: str
    content: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_version: str
    estimated_tokens: int = Field(ge=1)


class RankingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: PipelineStage
    ordinal: int = Field(ge=1)
    chunk_id: UUID | None = None
    document_id: UUID | None = None
    source_key: str | None = None
    input_score: float | None = None
    output_score: float | None = None
    action: DecisionAction
    reason_code: str = Field(min_length=1, max_length=128)
    components: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    source_version: str | None = None


class PipelineCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: UUID
    document_id: UUID
    source_key: str
    title: str
    content: str
    document_kind: RetrievalDocumentKind
    retrieval_score: float = Field(ge=0.0)
    rerank_score: float = Field(ge=0.0, le=1.0)
    final_rank: int = Field(ge=1)
    contributing_queries: list[str] = Field(min_length=1)
    channels: list[RetrievalChannel] = Field(min_length=1)
    source_version: str


class RetrievalPipelineTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    tenant_id: UUID
    pipeline_version: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis: QueryAnalysis
    retrieval_trace_ids: list[UUID]
    decisions: list[RankingDecision]
    selected_chunk_ids: list[UUID]
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalPipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[PipelineCandidate]
    context: list[ParentResolvedContext]
    trace: RetrievalPipelineTrace

from verideploy.rag.access.schemas import RequestedMetadataFilters
RetrievalPipelineRequest.model_rebuild()
QueryAnalysis.model_rebuild()
