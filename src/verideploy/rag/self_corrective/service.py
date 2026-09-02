from __future__ import annotations

import re
from uuid import uuid4

from verideploy.rag.access.schemas import RequestedMetadataFilters, RetrievalAuthorizationScope, build_effective_scope
from verideploy.rag.orchestration.schemas import RetrievalPipelineRequest
from verideploy.rag.orchestration.service import RetrievalPipeline
from .external import EXTERNAL_SEARCH_PERMISSION, ExternalSearchProvider
from .grading import grade_evidence
from .repository import SelfCorrectiveRunRepository
from .schemas import (
    CorrectiveAttempt, EvidenceGrade, ExternalSearchMode, SelfCorrectiveRAGRequest,
    SelfCorrectiveRAGResult, StopReason,
)

CONTROLLER_VERSION = "1.0.0"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_.:/-]+")


class SelfCorrectiveRAG:
    def __init__(self, *, pipeline: RetrievalPipeline, repository: SelfCorrectiveRunRepository, external_search: ExternalSearchProvider | None = None) -> None:
        self.pipeline = pipeline
        self.repository = repository
        self.external_search = external_search

    async def run(self, request: SelfCorrectiveRAGRequest, *, authorization: RetrievalAuthorizationScope) -> SelfCorrectiveRAGResult:
        if authorization.tenant_id != request.retrieval.tenant_id:
            raise PermissionError("self-corrective RAG tenant mismatch")
        run_id = uuid4()
        attempts: list[CorrectiveAttempt] = []
        current = request.retrieval.model_copy(deep=True)
        rewrites = 0
        relaxed = False
        best = None
        best_grade = None
        last_signature: tuple[int, int, float] | None = None
        stop_reason = StopReason.RETRY_BUDGET_EXHAUSTED

        for attempt_number in range(1, request.max_attempts + 1):
            effective = self._effective_scope(current, authorization)
            if effective.empty:
                # Contradictory requested metadata may be relaxed, but trusted authorization is never changed.
                if request.allow_requested_scope_relaxation and not relaxed and attempt_number < request.max_attempts:
                    current = self._relax_requested_scope(current)
                    relaxed = True
                    continue
                empty_result = await self.pipeline.run(current, authorization=authorization)
                grade = grade_evidence(empty_result)
                attempts.append(CorrectiveAttempt(attempt=attempt_number, query=current.query, action="authorization_empty", requested_scope_relaxed=relaxed, retrieval_run_id=empty_result.trace.run_id, grade=grade, effective_scope_fingerprint=effective.fingerprint()))
                best, best_grade, stop_reason = empty_result, grade, StopReason.AUTHORIZATION_EMPTY
                break

            result = await self.pipeline.run(current, authorization=authorization)
            grade = grade_evidence(result)
            attempts.append(CorrectiveAttempt(
                attempt=attempt_number, query=current.query, action="retrieve" if attempt_number == 1 else ("relax_requested_scope" if relaxed else "rewrite_query"),
                requested_scope_relaxed=relaxed, retrieval_run_id=result.trace.run_id, grade=grade,
                effective_scope_fingerprint=effective.fingerprint(), metadata={"pipeline_version": result.trace.pipeline_version},
            ))
            if best_grade is None or grade.score > best_grade.score:
                best, best_grade = result, grade
            if grade.grade is EvidenceGrade.SUFFICIENT:
                stop_reason = StopReason.SUFFICIENT_EVIDENCE
                break
            signature = (grade.candidate_count, grade.source_count, grade.top_rerank_score)
            no_progress = last_signature == signature
            last_signature = signature
            if attempt_number >= request.max_attempts:
                stop_reason = StopReason.RETRY_BUDGET_EXHAUSTED
                break
            if rewrites < request.max_query_rewrites:
                current = current.model_copy(update={"query": self._rewrite_query(current.query, grade.reasons, rewrites + 1)})
                rewrites += 1
                relaxed = False
                continue
            if request.allow_requested_scope_relaxation and not relaxed and self._has_requested_constraints(current):
                current = self._relax_requested_scope(current)
                relaxed = True
                continue
            if no_progress:
                stop_reason = StopReason.NO_PROGRESS
                break

        assert best is not None and best_grade is not None
        external_evidence = []
        if best_grade.grade is not EvidenceGrade.SUFFICIENT:
            if request.external_search_mode is ExternalSearchMode.DISABLED:
                if stop_reason not in {StopReason.AUTHORIZATION_EMPTY, StopReason.NO_PROGRESS}:
                    stop_reason = StopReason.EXTERNAL_SEARCH_DISABLED
            elif EXTERNAL_SEARCH_PERMISSION not in authorization.permissions:
                stop_reason = StopReason.EXTERNAL_SEARCH_UNAUTHORIZED
            elif self.external_search is None:
                stop_reason = StopReason.EXTERNAL_SEARCH_UNAVAILABLE
            else:
                external_evidence = await self.external_search.search(query=current.query, max_results=3)
                # External evidence is supplemental only in Self Corrective RAG; it never upgrades internal evidence to sufficient automatically.

        answerable = best_grade.grade is EvidenceGrade.SUFFICIENT
        qualification = None if answerable else (
            f"Insufficient authorized evidence: grade={best_grade.grade.value}, score={best_grade.score:.2f}; "
            f"stop_reason={stop_reason.value}. The result is intentionally qualified and should not be treated as a proven answer."
        )
        final = SelfCorrectiveRAGResult(
            run_id=run_id, tenant_id=request.retrieval.tenant_id, answerable=answerable, qualified=not answerable,
            qualification=qualification, stop_reason=stop_reason, attempts=attempts, final_retrieval=best,
            external_evidence=external_evidence, controller_version=CONTROLLER_VERSION,
        )
        self.repository.save(final)
        return final

    @staticmethod
    def _rewrite_query(query: str, reasons: tuple[str, ...], ordinal: int) -> str:
        normalized = " ".join(query.split())
        hints = []
        if "insufficient_source_corroboration" in reasons:
            hints.append("corroborating evidence")
        if "low_top_relevance" in reasons or "no_candidates" in reasons:
            hints.append("incident symptoms runbook")
        if "no_usable_context" in reasons:
            hints.append("operational context")
        suffix = " ".join(hints or ["engineering evidence"])
        rewritten = f"{normalized} {suffix}"
        # Keep bounded deterministic rewrites from accumulating repeated hints.
        tokens: list[str] = []
        for token in _TOKEN_RE.findall(rewritten):
            if token.casefold() not in {x.casefold() for x in tokens}:
                tokens.append(token)
        return " ".join(tokens)[:4000]

    @staticmethod
    def _effective_scope(request: RetrievalPipelineRequest, authorization: RetrievalAuthorizationScope):
        requested = request.metadata_filters.model_copy(deep=True) if request.metadata_filters else RequestedMetadataFilters()
        contradictory = False
        if request.service:
            value = request.service.casefold()
            if requested.services and value not in requested.services:
                contradictory = True
            requested.services = [value]
        if request.environment:
            value = request.environment.casefold()
            if requested.environments and value not in requested.environments:
                contradictory = True
            requested.environments = [value]
        if request.document_kinds:
            values = [kind.value for kind in request.document_kinds]
            if requested.document_kinds:
                intersection = [value for value in values if value in requested.document_kinds]
                if not intersection:
                    contradictory = True
                requested.document_kinds = intersection
            else:
                requested.document_kinds = values
        scope = build_effective_scope(authorization=authorization, requested=requested)
        return scope.model_copy(update={"empty": True}) if contradictory else scope

    @staticmethod
    def _has_requested_constraints(request: RetrievalPipelineRequest) -> bool:
        f = request.metadata_filters
        return bool(request.service or request.environment or request.document_kinds or (f and any((f.services, f.environments, f.document_kinds, f.severities, f.teams, f.occurred_from, f.occurred_to))))

    @staticmethod
    def _relax_requested_scope(request: RetrievalPipelineRequest) -> RetrievalPipelineRequest:
        # Relax all *requested* metadata while the trusted authorization object remains unchanged.
        return request.model_copy(update={"service": None, "environment": None, "document_kinds": [], "metadata_filters": RequestedMetadataFilters()})

    def get(self, *, tenant_id, run_id):
        return self.repository.get(tenant_id=tenant_id, run_id=run_id)
