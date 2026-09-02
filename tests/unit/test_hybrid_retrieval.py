from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from verideploy.rag.embeddings.schemas import EmbeddingBatchResult, EmbeddingRecord
from verideploy.rag.retrieval.benchmark import run_seed_benchmark
from verideploy.rag.retrieval.fusion import FusionConfig, normalize_scores, reciprocal_rank_fusion
from verideploy.rag.retrieval.repository import DenseRow, KeywordRow, RetrievalRepository
from verideploy.rag.retrieval.schemas import ChannelCandidate, RetrievalChannel, RetrievalQuery
from verideploy.rag.retrieval.service import HybridRetriever


def _candidate(rank: int, source: str, channel: RetrievalChannel, raw: float, normalized: float, chunk=None):
    chunk_id = chunk or uuid4()
    return ChannelCandidate(
        chunk_id=chunk_id, document_id=uuid4(), source_key=source, title=source, content=source,
        channel=channel, rank=rank, raw_score=raw, normalized_score=normalized,
    )


def test_score_normalization_handles_equal_and_distance_scores():
    assert normalize_scores([5, 5]) == [1.0, 1.0]
    assert normalize_scores([0.1, 0.9], higher_is_better=False) == [1.0, 0.0]


def test_rrf_rewards_cross_channel_agreement_and_records_contributions():
    shared = uuid4()
    keyword = [_candidate(1, "a", RetrievalChannel.KEYWORD, 5, 1, shared), _candidate(2, "b", RetrievalChannel.KEYWORD, 4, 0.5)]
    dense = [_candidate(1, "a", RetrievalChannel.DENSE, 0.1, 1, shared), _candidate(2, "c", RetrievalChannel.DENSE, 0.2, 0.5)]
    hits = reciprocal_rank_fusion(keyword, dense, top_k=3)
    assert hits[0].chunk_id == shared
    assert len(hits[0].contributions) == 2
    assert hits[0].fused_score == pytest.approx(2 / 61)


def test_rrf_enforces_source_diversity():
    keyword = [_candidate(i, "same", RetrievalChannel.KEYWORD, 10-i, 1-(i-1)*.1) for i in range(1, 5)]
    dense = [_candidate(1, "other", RetrievalChannel.DENSE, .1, 1)]
    hits = reciprocal_rank_fusion(keyword, dense, top_k=4, config=FusionConfig(max_per_source=2))
    assert sum(hit.source_key == "same" for hit in hits) == 2


class FakeRepo(RetrievalRepository):
    def __init__(self):
        self.model_id = uuid4()
        self.shared = uuid4()
        self.doc = uuid4()

    def keyword_search(self, **kwargs):
        return [KeywordRow(self.shared, self.doc, "runbook", "DB pool", "pool exhausted", 0.9)]

    def dense_search(self, **kwargs):
        return [DenseRow(self.shared, self.doc, "runbook", "DB pool", "pool exhausted", 0.05)]

    def get_embedding_model_id(self, **kwargs):
        return self.model_id


class FakePipeline:
    async def embed(self, request):
        return EmbeddingBatchResult(
            request_id=request.request_id, tenant_id=request.tenant_id, model=request.model or "m", dimensions=request.dimensions or 3,
            records=[EmbeddingRecord(tenant_id=request.tenant_id, content_hash="0"*64, model=request.model or "m", dimensions=request.dimensions or 3, registry_version=1, values=[0.1,0.2,0.3])],
            cache_hits=0, provider_input_count=1,
        )


@pytest.mark.asyncio
async def test_hybrid_service_returns_traceable_fusion():
    tenant = uuid4()
    result = await HybridRetriever(FakeRepo(), FakePipeline()).retrieve(
        RetrievalQuery(tenant_id=tenant, text="database pool", top_k=5, candidate_k=10, model_name="m", dimensions=3)
    )
    assert len(result.hits) == 1
    assert len(result.hits[0].contributions) == 2
    assert result.trace.keyword_candidates == 1
    assert result.trace.dense_candidates == 1
    assert result.trace.ranking[0]["chunk_id"] == str(result.hits[0].chunk_id)


def test_seed_benchmark_hybrid_meets_or_beats_single_channels():
    results = run_seed_benchmark()
    assert results["hybrid"].recall_at_5 >= max(results["keyword"].recall_at_5, results["dense"].recall_at_5)
    assert results["hybrid"].mrr >= max(results["keyword"].mrr, results["dense"].mrr)
