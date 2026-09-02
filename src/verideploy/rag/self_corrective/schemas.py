from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from verideploy.rag.orchestration.schemas import RetrievalPipelineRequest, RetrievalPipelineResult


class EvidenceGrade(StrEnum):
    SUFFICIENT = "sufficient"
    WEAK = "weak"
    INSUFFICIENT = "insufficient"


class StopReason(StrEnum):
    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    AUTHORIZATION_EMPTY = "authorization_empty"
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    NO_PROGRESS = "no_progress"
    EXTERNAL_SEARCH_DISABLED = "external_search_disabled"
    EXTERNAL_SEARCH_UNAUTHORIZED = "external_search_unauthorized"
    EXTERNAL_SEARCH_UNAVAILABLE = "external_search_unavailable"


class ExternalSearchMode(StrEnum):
    DISABLED = "disabled"
    AUTHORIZED_ONLY = "authorized_only"


class EvidenceGradeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    grade: EvidenceGrade
    score: float = Field(ge=0.0, le=1.0)
    candidate_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    context_count: int = Field(ge=0)
    top_rerank_score: float = Field(ge=0.0, le=1.0)
    reasons: tuple[str, ...] = ()


class SelfCorrectiveRAGRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retrieval: RetrievalPipelineRequest
    max_attempts: int = Field(default=3, ge=1, le=5)
    max_query_rewrites: int = Field(default=2, ge=0, le=4)
    allow_requested_scope_relaxation: bool = True
    external_search_mode: ExternalSearchMode = ExternalSearchMode.DISABLED


class CorrectiveAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt: int = Field(ge=1)
    query: str
    action: str
    requested_scope_relaxed: bool = False
    retrieval_run_id: UUID
    grade: EvidenceGradeResult
    effective_scope_fingerprint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    title: str
    content: str
    locator: str


class SelfCorrectiveRAGResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    tenant_id: UUID
    answerable: bool
    qualified: bool
    qualification: str | None = None
    stop_reason: StopReason
    attempts: list[CorrectiveAttempt]
    final_retrieval: RetrievalPipelineResult
    external_evidence: list[ExternalEvidence] = Field(default_factory=list)
    controller_version: str
