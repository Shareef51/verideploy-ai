from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from verideploy.rag.orchestration.repository import RetrievalPipelineTraceRepository
from verideploy.rag.orchestration.reranker import SemanticRerankDocument, SemanticReranker
from verideploy.rag.orchestration.schemas import (
    DecisionAction, ParentResolvedContext, PipelineCandidate, PipelineStage, QueryAnalysis,
    QuerySubproblem, RankingDecision, RetrievalPipelineRequest, RetrievalPipelineResult, RetrievalPipelineTrace,
)
from verideploy.rag.retrieval.schemas import HybridRetrievalResult, RetrievalChannel, RetrievalDocumentKind, RetrievalQuery
from verideploy.rag.access.schemas import RetrievalAuthorizationScope
from verideploy.observability.telemetry import traced_async

PIPELINE_VERSION = "1.0.0"
QUERY_ANALYZER_VERSION = "deterministic-v1"
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:/-]*", re.I)
STOP = {"the", "a", "an", "is", "are", "of", "to", "for", "in", "on", "and", "or", "with", "what", "why", "how"}


class RetrievalPort(Protocol):
    async def retrieve_mode(self, request: RetrievalQuery, *, mode: RetrievalChannel) -> HybridRetrievalResult: ...


class ParentResolverPort(Protocol):
    def resolve(self, *, tenant_id: UUID, chunk_id: UUID, fallback: str, source_key: str, title: str, document_id: UUID) -> ParentResolvedContext: ...


@dataclass(frozen=True)
class DeterministicParentResolver:
    def resolve(self, *, tenant_id: UUID, chunk_id: UUID, fallback: str, source_key: str, title: str, document_id: UUID) -> ParentResolvedContext:
        digest = hashlib.sha256(fallback.encode("utf-8")).hexdigest()
        return ParentResolvedContext(
            chunk_id=chunk_id, document_id=document_id, source_key=source_key, title=title,
            content=fallback, content_sha256=digest, source_version=digest, estimated_tokens=max(1, (len(fallback) + 3)//4),
        )


class RetrievalPipeline:
    def __init__(self, *, retriever: RetrievalPort, parent_resolver: ParentResolverPort, traces: RetrievalPipelineTraceRepository, semantic_reranker: SemanticReranker | None = None) -> None:
        self.retriever = retriever
        self.parent_resolver = parent_resolver
        self.traces = traces
        self.semantic_reranker = semantic_reranker

    def get_trace(self, *, tenant_id: UUID, run_id: UUID) -> RetrievalPipelineTrace | None:
        return self.traces.get(tenant_id=tenant_id, run_id=run_id)

    @traced_async("rag.retrieval_pipeline")
    async def run(self, request: RetrievalPipelineRequest, *, authorization: RetrievalAuthorizationScope | None = None) -> RetrievalPipelineResult:
        run_id = uuid4()
        analysis = self._analyze(request)
        decisions: list[RankingDecision] = []
        ordinal = 0

        def emit(stage: PipelineStage, action: DecisionAction, reason: str, **kwargs) -> None:
            nonlocal ordinal
            ordinal += 1
            decisions.append(RankingDecision(stage=stage, ordinal=ordinal, action=action, reason_code=reason, **kwargs))

        emit(PipelineStage.ANALYZE, DecisionAction.KEEP, "normalized_query", components={"token_count": len(analysis.tokens), "query_version": analysis.query_version})
        for expansion in analysis.expansions:
            emit(PipelineStage.EXPAND, DecisionAction.KEEP, "deterministic_expansion", components={"query": expansion})

        subproblems = analysis.subqueries or [self._strategy(analysis.normalized_query, "general", request)]
        merged: dict[UUID, dict] = {}
        trace_ids: list[UUID] = []
        async def retrieve(problem: QuerySubproblem):
            retrieval_request = RetrievalQuery(
                tenant_id=request.tenant_id, text=problem.question, top_k=min(problem.candidate_k, 100), candidate_k=problem.candidate_k,
                model_name=request.model_name, dimensions=request.dimensions, service=request.service,
                environment=request.environment, document_kinds=problem.document_kinds or request.document_kinds, metadata_filters=request.metadata_filters,
                keyword_weight=problem.keyword_weight, dense_weight=problem.dense_weight,
            )
            if authorization is None:
                result = await self.retriever.retrieve_mode(retrieval_request, mode=problem.retrieval_mode)
            else:
                try:
                    result = await self.retriever.retrieve_mode(retrieval_request, mode=problem.retrieval_mode, authorization=authorization)
                except TypeError as exc:
                    if "authorization" not in str(exc): raise
                    result = await self.retriever.retrieve_mode(retrieval_request, mode=problem.retrieval_mode)
            return problem, result

        retrieval_results = await asyncio.gather(*(retrieve(problem) for problem in subproblems))
        for problem, result in retrieval_results:
            query = problem.question
            if result.trace.tenant_id != request.tenant_id:
                raise PermissionError("retrieval result tenant mismatch")
            trace_ids.append(result.trace.trace_id)
            for hit in result.hits:
                channels = sorted({c.channel for c in hit.contributions}, key=lambda x: x.value)
                current = merged.get(hit.chunk_id)
                if current is None:
                    merged[hit.chunk_id] = {"hit": hit, "queries": [query], "channels": channels}
                else:
                    if query not in current["queries"]:
                        current["queries"].append(query)
                    current["channels"] = sorted(set(current["channels"]) | set(channels), key=lambda x: x.value)
                    if hit.fused_score > current["hit"].fused_score:
                        current["hit"] = hit
                emit(PipelineStage.RETRIEVE, DecisionAction.KEEP, "retrieval_candidate", chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, output_score=hit.fused_score, components={"query": query, "subquery_id": problem.subquery_id, "intent": problem.intent, "channels": ",".join(x.value for x in channels), "candidate_k": problem.candidate_k, "keyword_weight": problem.keyword_weight, "dense_weight": problem.dense_weight, "metadata_first": problem.metadata_first})

        fused = sorted(merged.values(), key=lambda x: (-x["hit"].fused_score, x["hit"].source_key, str(x["hit"].chunk_id)))
        for item in fused:
            hit = item["hit"]
            emit(PipelineStage.FUSE, DecisionAction.SCORE, "best_cross_query_score", chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, input_score=hit.fused_score, output_score=hit.fused_score, components={"query_count": len(item["queries"])})

        reranked: list[tuple[float, dict]] = []
        semantic_scores: dict[UUID, float] | None = None
        reranker_error: str | None = None
        if self.semantic_reranker is not None and fused:
            try:
                semantic_scores = await self.semantic_reranker.rerank(tenant_id=request.tenant_id, correlation_id=str(run_id), query=analysis.normalized_query, documents=[SemanticRerankDocument(chunk_id=x["hit"].chunk_id, title=x["hit"].title, content=x["hit"].content) for x in fused], model=request.model_name, dimensions=request.dimensions)
                if set(semantic_scores) != {x["hit"].chunk_id for x in fused} or any(not 0 <= score <= 1 for score in semantic_scores.values()):
                    raise ValueError("semantic reranker returned incomplete or unnormalized scores")
            except Exception as exc:
                semantic_scores = None
                reranker_error = type(exc).__name__
        query_tokens = set(analysis.tokens)
        for item in fused:
            hit = item["hit"]
            if semantic_scores is not None:
                score = round(semantic_scores[hit.chunk_id], 8)
                reason = "semantic_model_rerank"
                components = {"semantic_score": score}
            else:
                text_tokens = set(TOKEN_RE.findall((hit.title + " " + hit.content).casefold()))
                overlap = len(query_tokens & text_tokens) / max(1, len(query_tokens))
                retrieval_norm = min(1.0, hit.fused_score * 60.0)
                score = round((0.72 * retrieval_norm) + (0.28 * overlap), 8)
                reason = "transparent_weighted_rerank_fallback"
                components = {"retrieval_norm": round(retrieval_norm, 8), "lexical_overlap": round(overlap, 8), "retrieval_weight": 0.72, "overlap_weight": 0.28, "fallback_error": reranker_error or "reranker_not_configured"}
            reranked.append((score, item))
            emit(PipelineStage.RERANK, DecisionAction.SCORE, reason, chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, input_score=hit.fused_score, output_score=score, components=components)
        reranked.sort(key=lambda x: (-x[0], x[1]["hit"].source_key, str(x[1]["hit"].chunk_id)))

        filtered: list[tuple[float, dict]] = []
        for score, item in reranked:
            hit = item["hit"]
            keep = score >= request.min_rerank_score
            emit(PipelineStage.FILTER, DecisionAction.KEEP if keep else DecisionAction.DROP, "meets_min_rerank_score" if keep else "below_min_rerank_score", chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, input_score=score, output_score=score, components={"threshold": request.min_rerank_score})
            if keep:
                filtered.append((score, item))

        diversified: list[tuple[float, dict]] = []
        per_source: dict[str, int] = defaultdict(int)
        for score, item in filtered:
            hit = item["hit"]
            if per_source[hit.source_key] >= request.max_per_source:
                emit(PipelineStage.DIVERSIFY, DecisionAction.DROP, "source_diversity_limit", chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, input_score=score, output_score=score, components={"max_per_source": request.max_per_source})
                continue
            per_source[hit.source_key] += 1
            diversified.append((score, item))
            emit(PipelineStage.DIVERSIFY, DecisionAction.KEEP, "source_diversity_kept", chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, input_score=score, output_score=score, components={"source_count": per_source[hit.source_key]})
            if len(diversified) >= request.top_k:
                break

        contexts: list[ParentResolvedContext] = []
        candidates: list[PipelineCandidate] = []
        token_total = 0
        for rank, (score, item) in enumerate(diversified, start=1):
            hit = item["hit"]
            parent = self.parent_resolver.resolve(tenant_id=request.tenant_id, chunk_id=hit.chunk_id, fallback=hit.content, source_key=hit.source_key, title=hit.title, document_id=hit.document_id)
            emit(PipelineStage.PARENT_RESOLVE, DecisionAction.KEEP, "parent_context_resolved", chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, input_score=score, output_score=score, source_version=parent.source_version, components={"content_sha256": parent.content_sha256, "estimated_tokens": parent.estimated_tokens})
            if token_total + parent.estimated_tokens > request.context_token_budget:
                emit(PipelineStage.CONTEXT_BUILD, DecisionAction.DROP, "context_token_budget_exceeded", chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, input_score=score, output_score=score, source_version=parent.source_version, components={"budget": request.context_token_budget, "used": token_total, "candidate_tokens": parent.estimated_tokens})
                continue
            token_total += parent.estimated_tokens
            contexts.append(parent)
            emit(PipelineStage.CONTEXT_BUILD, DecisionAction.SELECT, "context_selected", chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, input_score=score, output_score=score, source_version=parent.source_version, components={"context_position": len(contexts), "cumulative_tokens": token_total})
            candidates.append(PipelineCandidate(
                chunk_id=hit.chunk_id, document_id=hit.document_id, source_key=hit.source_key, title=hit.title,
                content=hit.content, document_kind=hit.document_kind, retrieval_score=hit.fused_score,
                rerank_score=score, final_rank=len(candidates)+1, contributing_queries=item["queries"],
                channels=item["channels"], source_version=parent.source_version,
            ))

        input_sha = hashlib.sha256(json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        context_sha = hashlib.sha256(json.dumps([c.model_dump(mode="json") for c in contexts], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        trace = RetrievalPipelineTrace(
            run_id=run_id, tenant_id=request.tenant_id, pipeline_version=PIPELINE_VERSION,
            input_sha256=input_sha, analysis=analysis, retrieval_trace_ids=trace_ids, decisions=decisions,
            selected_chunk_ids=[c.chunk_id for c in candidates], context_sha256=context_sha,
            metadata={"query_count": len(subproblems), "candidate_count": len(merged), "context_tokens": token_total, "query_purpose": request.query_purpose, "retrieval_concurrency": len(subproblems), "reranker_mode": "semantic" if semantic_scores is not None else "heuristic_fallback", "rerank_formula": "semantic_model" if semantic_scores is not None else "0.72*min(1,fused_score*60)+0.28*lexical_overlap", "reranker_error": reranker_error},
        )
        self.traces.save(trace)
        return RetrievalPipelineResult(candidates=candidates, context=contexts, trace=trace)

    @staticmethod
    def _analyze(request: RetrievalPipelineRequest) -> QueryAnalysis:
        normalized = " ".join(request.query.split())
        tokens = [t for t in TOKEN_RE.findall(normalized.casefold()) if t not in STOP]
        unique: list[str] = []
        for token in tokens:
            if token not in unique:
                unique.append(token)
        expansions: list[str] = []
        qualifiers = [x for x in (request.service, request.environment) if x]
        if qualifiers and request.max_expansions > 0:
            candidate = f"{normalized} {' '.join(qualifiers)}"
            if candidate.casefold() != normalized.casefold(): expansions.append(candidate)
        if request.document_kinds and len(expansions) < request.max_expansions:
            candidate = f"{normalized} {' '.join(k.value.replace('_',' ') for k in request.document_kinds)}"
            if all(candidate.casefold() != x.casefold() for x in [normalized, *expansions]): expansions.append(candidate)
        if request.query_purpose == "incident_rca":
            service = request.service or "the affected service"
            questions = [
                ("change", f"What changed immediately before the incident affecting {service}?"),
                ("telemetry", f"Which service shows abnormal telemetry related to: {normalized}"),
                ("history", f"Are there matching historical incidents for: {normalized}"),
                ("architecture", f"What architecture dependency connects {service} to the affected components?"),
                ("runbook", f"Does a runbook describe the symptom: {normalized}"),
                ("contradiction", f"What evidence contradicts the leading explanation for: {normalized}"),
            ][:request.max_subqueries]
            subqueries = [RetrievalPipeline._strategy(question, intent, request, index=i + 1) for i, (intent, question) in enumerate(questions)]
        else:
            questions = [normalized, *expansions[:request.max_expansions]]
            subqueries = [RetrievalPipeline._strategy(question, "general", request, index=i + 1) for i, question in enumerate(questions)]
        return QueryAnalysis(normalized_query=normalized, tokens=unique, expansions=expansions[:request.max_expansions], query_version=QUERY_ANALYZER_VERSION, subqueries=subqueries)

    @staticmethod
    def _strategy(question: str, intent: str, request: RetrievalPipelineRequest, *, index: int = 1) -> QuerySubproblem:
        error_like = bool(re.search(r"\b(?:error|exception|traceback|[A-Z]{2,8}-?\d{3,}|5\d\d)\b", question, re.I))
        conceptual = intent == "architecture" or bool(re.search(r"\b(?:architecture|dependency|design|connects?)\b", question, re.I))
        if error_like:
            keyword, dense, mode, candidate_k = .7, .3, RetrievalChannel.HYBRID, min(100, max(40, request.candidate_k))
        elif conceptual:
            keyword, dense, mode, candidate_k = .25, .75, RetrievalChannel.HYBRID, min(100, max(60, request.candidate_k))
        else:
            keyword, dense, mode, candidate_k = .5, .5, request.retrieval_mode, min(100, max(40, request.candidate_k))
        kinds = {"history": [RetrievalDocumentKind.HISTORICAL_INCIDENT], "architecture": [RetrievalDocumentKind.ARCHITECTURE], "runbook": [RetrievalDocumentKind.RUNBOOK]}.get(intent, request.document_kinds)
        return QuerySubproblem(subquery_id=f"q{index}", question=question, intent=intent, retrieval_mode=mode, candidate_k=candidate_k, keyword_weight=keyword, dense_weight=dense, document_kinds=kinds, metadata_first=bool(request.service and request.environment))
