from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from verideploy.rag.retrieval.schemas import (
    HybridHit,
    HybridRetrievalResult,
    RetrievalChannel,
    RetrievalDocumentKind,
    RetrievalQuery,
    RetrievalTrace,
)

from .base import BaseAgent
from .contracts import AgentAuthorization, AgentName, AgentRequest, ToolBudget, ToolPermission


class RAGIntent(StrEnum):
    HISTORICAL_INCIDENT = "historical_incident"
    RUNBOOK = "runbook"
    ARCHITECTURE = "architecture"
    GENERAL = "general"


class RAGQueryAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    normalized_query: str = Field(min_length=1, max_length=4_000)
    intent: RAGIntent
    retrieval_mode: RetrievalChannel
    document_kinds: list[RetrievalDocumentKind] = Field(min_length=1, max_length=4)
    service: str | None = Field(default=None, max_length=120)
    environment: str | None = Field(default=None, max_length=80)
    query_expansions: list[str] = Field(default_factory=list, max_length=3)
    top_k: int = Field(default=8, ge=1, le=20)
    rationale: str = Field(min_length=1, max_length=4_000)

    @field_validator("intent", "retrieval_mode", mode="before")
    @classmethod
    def decode_enum(cls, value, info):
        enum_type = RAGIntent if info.field_name == "intent" else RetrievalChannel
        return enum_type(value) if isinstance(value, str) else value

    @field_validator("document_kinds", mode="before")
    @classmethod
    def decode_kinds(cls, value):
        return [RetrievalDocumentKind(item) if isinstance(item, str) else item for item in (value or [])]

    @field_validator("query_expansions")
    @classmethod
    def unique_nonblank_expansions(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("query expansions must not be blank")
            key = text.casefold()
            if key in seen:
                raise ValueError("duplicate query expansion")
            seen.add(key)
            cleaned.append(text)
        return cleaned

    @model_validator(mode="after")
    def intent_kind_consistency(self) -> "RAGQueryAnalysis":
        expected = {
            RAGIntent.HISTORICAL_INCIDENT: RetrievalDocumentKind.HISTORICAL_INCIDENT,
            RAGIntent.RUNBOOK: RetrievalDocumentKind.RUNBOOK,
            RAGIntent.ARCHITECTURE: RetrievalDocumentKind.ARCHITECTURE,
        }.get(self.intent)
        if expected is not None and expected not in self.document_kinds:
            raise ValueError("intent must include its matching document kind")
        return self


class RAGEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    chunk_id: UUID
    document_id: UUID
    document_kind: RetrievalDocumentKind
    source_key: str
    title: str
    content: str
    rank: int = Field(ge=1)
    score: float = Field(gt=0)
    contributing_queries: list[str] = Field(min_length=1)
    channels: list[RetrievalChannel] = Field(min_length=1)


class EvidenceSufficiency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sufficient: bool
    evidence_count: int = Field(ge=0)
    unique_sources: int = Field(ge=0)
    covered_document_kinds: list[RetrievalDocumentKind]
    required_document_kinds: list[RetrievalDocumentKind]
    reason_codes: list[str]


class RAGAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: RAGQueryAnalysis
    evidence: list[RAGEvidenceItem]
    sufficiency: EvidenceSufficiency
    retrieval_traces: list[RetrievalTrace]
    tool_calls_used: int = Field(ge=0, le=64)


class RAGRetrievalPort(Protocol):
    async def retrieve(self, request: RetrievalQuery, *, mode: RetrievalChannel) -> HybridRetrievalResult: ...


class RAGAgent(BaseAgent[RAGQueryAnalysis]):
    model_name="role:fast"; reasoning_setting="low"
    agent_name = AgentName.RAG
    prompt_name = "rag"
    prompt_version = "1.0.0"
    output_model = RAGQueryAnalysis
    schema_name = "agent_rag_query_analysis"

    def __init__(self, *, model, prompts, repository, retrieval: RAGRetrievalPort) -> None:
        super().__init__(model=model, prompts=prompts, repository=repository)
        self.retrieval = retrieval

    async def run(
        self,
        request: AgentRequest,
        *,
        authorization: AgentAuthorization,
        budget: ToolBudget,
        model_name: str,
        dimensions: int,
        candidate_k: int,
        min_evidence: int = 2,
        min_sources: int = 1,
    ) -> RAGAgentResult:
        authorization.require([ToolPermission.RAG_RETRIEVAL_READ])
        analysis, run = await self._generate(
            request,
            authorization=authorization,
            budget=budget,
            payload={
                "objective": request.objective,
                "context": request.context,
                "allowed_document_kinds": [item.value for item in RetrievalDocumentKind],
                "allowed_retrieval_modes": [item.value for item in RetrievalChannel],
                "max_query_expansions": 3,
                "tool_budget": budget.max_calls,
            },
        )
        active_budget = budget
        try:
            self._validate_scope(request, analysis)
            queries = [analysis.normalized_query, *analysis.query_expansions]
            effective_service = request.context.get("service") or analysis.service
            effective_environment = request.context.get("environment") or analysis.environment
            if len(queries) > budget.remaining:
                raise RuntimeError("RAG retrieval plan exceeds tool-call budget")

            traces: list[RetrievalTrace] = []
            merged: dict[UUID, tuple[HybridHit, list[str]]] = {}
            for query_text in queries:
                active_budget = active_budget.consume()
                result = await self.retrieval.retrieve(
                    RetrievalQuery(
                        tenant_id=request.tenant_id,
                        text=query_text,
                        top_k=analysis.top_k,
                        candidate_k=max(candidate_k, analysis.top_k),
                        model_name=model_name,
                        dimensions=dimensions,
                        service=effective_service,
                        environment=effective_environment,
                        document_kinds=analysis.document_kinds,
                    ),
                    mode=analysis.retrieval_mode,
                )
                if result.trace.tenant_id != request.tenant_id:
                    raise PermissionError("retrieval result tenant mismatch")
                traces.append(result.trace)
                for hit in result.hits:
                    current = merged.get(hit.chunk_id)
                    if current is None:
                        merged[hit.chunk_id] = (hit, [query_text])
                    else:
                        best, contributing = current
                        if query_text not in contributing:
                            contributing.append(query_text)
                        if hit.fused_score > best.fused_score:
                            best = hit
                        merged[hit.chunk_id] = (best, contributing)

            ranked = sorted(
                merged.values(),
                key=lambda item: (-item[0].fused_score, item[0].source_key, str(item[0].chunk_id)),
            )[: analysis.top_k]
            evidence = [self._evidence(request.tenant_id, hit, queries) for hit, queries in ranked]
            sufficiency = self._assess_sufficiency(
                evidence,
                required_kinds=analysis.document_kinds,
                min_evidence=min_evidence,
                min_sources=min_sources,
            )
            result = RAGAgentResult(
                analysis=analysis,
                evidence=evidence,
                sufficiency=sufficiency,
                retrieval_traces=traces,
                tool_calls_used=active_budget.calls_used,
            )
            self.repository.complete(
                tenant_id=request.tenant_id,
                run_id=run.run_id,
                output=result.model_dump(mode="json"),
                tool_calls_used=active_budget.calls_used,
            )
            return result
        except Exception as exc:
            self.repository.fail(
                tenant_id=request.tenant_id,
                run_id=run.run_id,
                error_code=type(exc).__name__,
                tool_calls_used=active_budget.calls_used,
            )
            raise

    @staticmethod
    def _validate_scope(request: AgentRequest, analysis: RAGQueryAnalysis) -> None:
        trusted_service = request.context.get("service")
        trusted_environment = request.context.get("environment")
        if trusted_service is not None and analysis.service not in {None, trusted_service}:
            raise PermissionError("RAG service filter cannot broaden trusted request scope")
        if trusted_environment is not None and analysis.environment not in {None, trusted_environment}:
            raise PermissionError("RAG environment filter cannot broaden trusted request scope")

    @staticmethod
    def _evidence(tenant_id: UUID, hit: HybridHit, queries: list[str]) -> RAGEvidenceItem:
        evidence_id = uuid5(NAMESPACE_URL, f"{tenant_id}:rag:{hit.chunk_id}")
        channels = sorted({item.channel for item in hit.contributions}, key=lambda item: item.value)
        return RAGEvidenceItem(
            evidence_id=evidence_id,
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            document_kind=hit.document_kind,
            source_key=hit.source_key,
            title=hit.title,
            content=hit.content,
            rank=hit.rank,
            score=hit.fused_score,
            contributing_queries=queries,
            channels=channels,
        )

    @staticmethod
    def _assess_sufficiency(
        evidence: list[RAGEvidenceItem],
        *,
        required_kinds: list[RetrievalDocumentKind],
        min_evidence: int,
        min_sources: int,
    ) -> EvidenceSufficiency:
        covered = sorted({item.document_kind for item in evidence}, key=lambda item: item.value)
        sources = {item.source_key for item in evidence}
        reasons: list[str] = []
        if len(evidence) < min_evidence:
            reasons.append("insufficient_evidence_count")
        if len(sources) < min_sources:
            reasons.append("insufficient_source_diversity")
        missing = set(required_kinds) - set(covered)
        if missing:
            reasons.append("required_document_kind_missing")
        return EvidenceSufficiency(
            sufficient=not reasons,
            evidence_count=len(evidence),
            unique_sources=len(sources),
            covered_document_kinds=covered,
            required_document_kinds=required_kinds,
            reason_codes=reasons or ["sufficient"],
        )
