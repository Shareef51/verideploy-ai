from __future__ import annotations

import hashlib, inspect, json
from uuid import uuid4

from verideploy.rag.embeddings.pipeline import EmbeddingPipeline
from verideploy.rag.embeddings.schemas import EmbeddingInput, EmbeddingRequest
from verideploy.rag.retrieval.fusion import FusionConfig, normalize_scores, reciprocal_rank_fusion
from verideploy.rag.retrieval.repository import RetrievalRepository
from verideploy.rag.access import RequestedMetadataFilters, RetrievalAuthorizationScope, ScopedRetrievalCache, build_effective_scope
from verideploy.rag.access.schemas import READ_PERMISSION
from verideploy.rag.retrieval.schemas import (
    ChannelCandidate,
    HybridRetrievalResult,
    RetrievalChannel,
    RetrievalQuery,
    RetrievalTrace,
)


class HybridRetriever:
    def __init__(
        self,
        repository: RetrievalRepository,
        embedding_pipeline: EmbeddingPipeline,
        *,
        rrf_k: int = 60,
        max_per_source: int = 2,
        cache: ScopedRetrievalCache[HybridRetrievalResult] | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_pipeline = embedding_pipeline
        self.config = FusionConfig(rrf_k=rrf_k, max_per_source=max_per_source)
        self.cache = cache or ScopedRetrievalCache()

    async def retrieve(self, request: RetrievalQuery, *, authorization: RetrievalAuthorizationScope | None = None) -> HybridRetrievalResult:
        return await self.retrieve_mode(request, mode=RetrievalChannel.HYBRID, authorization=authorization)

    async def retrieve_mode(
        self, request: RetrievalQuery, *, mode: RetrievalChannel, authorization: RetrievalAuthorizationScope | None = None
    ) -> HybridRetrievalResult:
        authorization = authorization or RetrievalAuthorizationScope(tenant_id=request.tenant_id, permissions=frozenset({READ_PERMISSION}))
        if authorization.tenant_id != request.tenant_id:
            raise PermissionError("retrieval authorization tenant mismatch")
        requested = request.metadata_filters or RequestedMetadataFilters()
        legacy = requested.model_copy(deep=True)
        contradictory = False
        if request.service:
            value=request.service.casefold()
            if legacy.services and value not in legacy.services: contradictory=True
            legacy.services=[value]
        if request.environment:
            value=request.environment.casefold()
            if legacy.environments and value not in legacy.environments: contradictory=True
            legacy.environments=[value]
        if request.document_kinds:
            values=[x.value for x in request.document_kinds]
            if legacy.document_kinds:
                intersection=[x for x in values if x in legacy.document_kinds]
                if not intersection: contradictory=True
                legacy.document_kinds=intersection
            else:
                legacy.document_kinds=values
        scope = build_effective_scope(authorization=authorization, requested=legacy)
        if contradictory: scope=scope.model_copy(update={"empty":True})
        cache_key = hashlib.sha256(json.dumps({"request":request.model_dump(mode="json"),"mode":mode.value},sort_keys=True,separators=(",",":")).encode()).hexdigest()
        cached = self.cache.get(cache_key, scope)
        if inspect.isawaitable(cached): cached = await cached
        if cached is not None:
            cached.trace.cache_hit = True
            return cached
        keyword: list[ChannelCandidate] = []
        dense: list[ChannelCandidate] = []
        if mode in {RetrievalChannel.KEYWORD, RetrievalChannel.HYBRID}:
            keyword = self._keyword(request, scope)
        if mode in {RetrievalChannel.DENSE, RetrievalChannel.HYBRID}:
            dense = await self._dense(request, scope)

        fusion_config = FusionConfig(rrf_k=request.rrf_k, max_per_source=self.config.max_per_source, keyword_weight=request.keyword_weight, dense_weight=request.dense_weight)
        hits = reciprocal_rank_fusion(keyword, dense, top_k=request.top_k, config=fusion_config)
        ranking = [
            {
                "chunk_id": str(hit.chunk_id),
                "rank": hit.rank,
                "fused_score": hit.fused_score,
                "document_kind": hit.document_kind.value,
                "contributions": [item.model_dump(mode="json") for item in hit.contributions],
            }
            for hit in hits
        ]
        result = HybridRetrievalResult(
            hits=hits,
            trace=RetrievalTrace(
                tenant_id=request.tenant_id,
                query_text=request.text,
                keyword_candidates=len(keyword),
                dense_candidates=len(dense),
                rrf_k=request.rrf_k,
                source_diversity_limit=self.config.max_per_source,
                selected_chunk_ids=[hit.chunk_id for hit in hits],
                ranking=ranking, scope_fingerprint=scope.fingerprint(), effective_filters=scope.model_dump(mode="json"), cache_hit=False,
            ),
        )
        stored = self.cache.put(cache_key, scope, result)
        if inspect.isawaitable(stored): await stored
        return result

    def _keyword(self, request: RetrievalQuery, scope) -> list[ChannelCandidate]:
        rows = self.repository.keyword_search(
            tenant_id=request.tenant_id,
            query=request.text,
            limit=request.candidate_k,
            service=request.service,
            environment=request.environment,
            document_kinds=request.document_kinds or None,
            **({"effective_scope": scope} if getattr(self.repository,"supports_scope",False) else {}),
        )
        normalized = normalize_scores([row.score for row in rows])
        return [
            ChannelCandidate(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                source_key=row.source_key,
                title=row.title,
                content=row.content,
                channel=RetrievalChannel.KEYWORD,
                rank=index + 1,
                raw_score=row.score,
                normalized_score=normalized[index],
                document_kind=row.document_kind,
            )
            for index, row in enumerate(rows)
        ]

    async def _dense(self, request: RetrievalQuery, scope) -> list[ChannelCandidate]:
        embedding_result = await self.embedding_pipeline.embed(
            EmbeddingRequest(
                tenant_id=request.tenant_id,
                request_id=uuid4(),
                correlation_id=f"retrieval-{uuid4()}",
                model=request.model_name,
                dimensions=request.dimensions,
                inputs=[EmbeddingInput(text=request.text)],
            )
        )
        query_vector = embedding_result.records[0].values
        model_id = self.repository.get_embedding_model_id(
            tenant_id=request.tenant_id,
            model_name=request.model_name,
            dimensions=request.dimensions,
        )
        rows = self.repository.dense_search(
            tenant_id=request.tenant_id,
            embedding_model_id=model_id,
            query_vector=query_vector,
            limit=request.candidate_k,
            service=request.service,
            environment=request.environment,
            document_kinds=request.document_kinds or None,
            **({"effective_scope": scope} if getattr(self.repository,"supports_scope",False) else {}),
        )
        normalized = normalize_scores([row.distance for row in rows], higher_is_better=False)
        return [
            ChannelCandidate(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                source_key=row.source_key,
                title=row.title,
                content=row.content,
                channel=RetrievalChannel.DENSE,
                rank=index + 1,
                raw_score=row.distance,
                normalized_score=normalized[index],
                document_kind=row.document_kind,
            )
            for index, row in enumerate(rows)
        ]
