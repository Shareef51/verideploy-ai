from __future__ import annotations

from uuid import uuid4
import pytest

from verideploy.rag.orchestration.repository import MemoryRetrievalPipelineTraceRepository
from verideploy.rag.orchestration.schemas import DecisionAction, PipelineStage, RetrievalPipelineRequest
from verideploy.rag.orchestration.service import DeterministicParentResolver, RetrievalPipeline
from verideploy.rag.retrieval.schemas import (
    HybridHit, HybridRetrievalResult, RankingContribution, RetrievalChannel, RetrievalDocumentKind, RetrievalTrace
)


class FakeRetriever:
    def __init__(self, hits): self.hits=hits; self.calls=[]
    async def retrieve_mode(self, request, *, mode):
        self.calls.append((request, mode))
        return HybridRetrievalResult(
            hits=self.hits,
            trace=RetrievalTrace(
                tenant_id=request.tenant_id, query_text=request.text, keyword_candidates=len(self.hits),
                dense_candidates=len(self.hits), rrf_k=60, source_diversity_limit=2,
                selected_chunk_ids=[h.chunk_id for h in self.hits], ranking=[],
            ),
        )


class FakeSemanticReranker:
    async def rerank(self, **kwargs):
        return {document.chunk_id: index / 10 + .7 for index, document in enumerate(kwargs["documents"])}


def hit(*, source='runbook://checkout', score=.02, content='checkout database pool saturation connections latency', kind=RetrievalDocumentKind.RUNBOOK):
    return HybridHit(
        chunk_id=uuid4(), document_id=uuid4(), source_key=source, title='Checkout runbook', content=content,
        rank=1, fused_score=score, document_kind=kind,
        contributions=[RankingContribution(channel=RetrievalChannel.KEYWORD, rank=1, raw_score=.7, normalized_score=.8, rrf_contribution=score)],
    )


def req(tenant, **kw):
    data=dict(tenant_id=tenant, query='Why is checkout database latency high?', service='checkout', environment='production',
              document_kinds=[RetrievalDocumentKind.RUNBOOK], retrieval_mode=RetrievalChannel.HYBRID,
              top_k=4,candidate_k=10,max_expansions=2,max_per_source=2,min_rerank_score=.1,context_token_budget=2000,
              model_name='text-embedding-3-large',dimensions=3072)
    data.update(kw); return RetrievalPipelineRequest(**data)


@pytest.mark.asyncio
async def test_full_pipeline_runs_all_required_stages_and_persists_trace():
    tenant=uuid4(); traces=MemoryRetrievalPipelineTraceRepository(); retriever=FakeRetriever([hit()])
    result=await RetrievalPipeline(retriever=retriever,parent_resolver=DeterministicParentResolver(),traces=traces).run(req(tenant))
    stages={d.stage for d in result.trace.decisions}
    assert set(PipelineStage).issubset(stages)
    assert len(retriever.calls)==3  # base + service/environment + document-kind expansion
    stored=traces.get(tenant_id=tenant,run_id=result.trace.run_id)
    assert stored is not None and stored.context_sha256==result.trace.context_sha256


@pytest.mark.asyncio
async def test_rerank_score_is_reconstructable_from_stored_components():
    tenant=uuid4(); result=await RetrievalPipeline(retriever=FakeRetriever([hit(score=.015)]),parent_resolver=DeterministicParentResolver(),traces=MemoryRetrievalPipelineTraceRepository()).run(req(tenant))
    decision=next(d for d in result.trace.decisions if d.stage is PipelineStage.RERANK)
    c=decision.components
    reconstructed=round(.72*float(c['retrieval_norm'])+.28*float(c['lexical_overlap']),8)
    assert reconstructed==decision.output_score==result.candidates[0].rerank_score
    assert c['retrieval_weight']==.72 and c['overlap_weight']==.28


@pytest.mark.asyncio
async def test_semantic_reranker_is_primary_and_traced():
    tenant=uuid4(); hits=[hit(source="first"), hit(source="second")]
    result=await RetrievalPipeline(retriever=FakeRetriever(hits),parent_resolver=DeterministicParentResolver(),traces=MemoryRetrievalPipelineTraceRepository(),semantic_reranker=FakeSemanticReranker()).run(req(tenant,max_expansions=0))
    assert result.candidates[0].chunk_id == hits[1].chunk_id
    assert result.trace.metadata["reranker_mode"] == "semantic"
    assert all(d.reason_code == "semantic_model_rerank" for d in result.trace.decisions if d.stage is PipelineStage.RERANK)


@pytest.mark.asyncio
async def test_incident_rca_decomposes_into_six_adaptive_questions():
    tenant=uuid4(); retriever=FakeRetriever([hit()])
    result=await RetrievalPipeline(retriever=retriever,parent_resolver=DeterministicParentResolver(),traces=MemoryRetrievalPipelineTraceRepository()).run(req(tenant,query_purpose="incident_rca",max_expansions=0))
    assert [x.intent for x in result.trace.analysis.subqueries] == ["change","telemetry","history","architecture","runbook","contradiction"]
    assert len(retriever.calls) == 6 and result.trace.metadata["retrieval_concurrency"] == 6
    architecture=result.trace.analysis.subqueries[3]
    assert (architecture.keyword_weight, architecture.dense_weight) == (.25, .75)
    assert all(x.metadata_first for x in result.trace.analysis.subqueries)


@pytest.mark.asyncio
async def test_filter_records_explicit_drop_reason():
    tenant=uuid4(); h=hit(score=.001,content='unrelated material')
    result=await RetrievalPipeline(retriever=FakeRetriever([h]),parent_resolver=DeterministicParentResolver(),traces=MemoryRetrievalPipelineTraceRepository()).run(req(tenant,min_rerank_score=.95))
    assert result.candidates==[]
    assert any(d.stage is PipelineStage.FILTER and d.action is DecisionAction.DROP and d.reason_code=='below_min_rerank_score' for d in result.trace.decisions)


@pytest.mark.asyncio
async def test_diversification_caps_same_source_and_traces_drop():
    tenant=uuid4(); hits=[hit(source='same',score=.02),hit(source='same',score=.019),hit(source='other',score=.018)]
    result=await RetrievalPipeline(retriever=FakeRetriever(hits),parent_resolver=DeterministicParentResolver(),traces=MemoryRetrievalPipelineTraceRepository()).run(req(tenant,max_per_source=1,max_expansions=0))
    assert {c.source_key for c in result.candidates}=={'same','other'}
    assert sum(1 for c in result.candidates if c.source_key=='same')==1
    assert any(d.stage is PipelineStage.DIVERSIFY and d.reason_code=='source_diversity_limit' for d in result.trace.decisions)


@pytest.mark.asyncio
async def test_context_budget_drop_is_traceable():
    tenant=uuid4(); h=hit(content='database latency '*300)
    result=await RetrievalPipeline(retriever=FakeRetriever([h]),parent_resolver=DeterministicParentResolver(),traces=MemoryRetrievalPipelineTraceRepository()).run(req(tenant,max_expansions=0,context_token_budget=128))
    assert result.context==[] and result.candidates==[]
    assert any(d.stage is PipelineStage.CONTEXT_BUILD and d.reason_code=='context_token_budget_exceeded' for d in result.trace.decisions)


@pytest.mark.asyncio
async def test_parent_resolution_records_content_hash_and_source_version():
    tenant=uuid4(); result=await RetrievalPipeline(retriever=FakeRetriever([hit()]),parent_resolver=DeterministicParentResolver(),traces=MemoryRetrievalPipelineTraceRepository()).run(req(tenant,max_expansions=0))
    parent=next(d for d in result.trace.decisions if d.stage is PipelineStage.PARENT_RESOLVE)
    assert len(parent.source_version)==64 and len(parent.components['content_sha256'])==64
    assert result.candidates[0].source_version==parent.source_version


@pytest.mark.asyncio
async def test_trace_repository_is_immutable_by_copy():
    tenant=uuid4(); traces=MemoryRetrievalPipelineTraceRepository()
    result=await RetrievalPipeline(retriever=FakeRetriever([hit()]),parent_resolver=DeterministicParentResolver(),traces=traces).run(req(tenant,max_expansions=0))
    result.trace.metadata['tampered']=True
    stored=traces.get(tenant_id=tenant,run_id=result.trace.run_id)
    assert 'tampered' not in stored.metadata


def test_migration_persists_runs_decisions_rls_and_append_only():
    src=open('src/verideploy/database/migrations/versions/0016_retrieval_pipeline_orchestration.py').read()
    for token in ('retrieval_pipeline_runs','retrieval_ranking_decisions','FORCE ROW LEVEL SECURITY','prevent_trace_mutation','input_sha256','context_sha256','source_version'):
        assert token in src
    assert 'down_revision = "0015_milestone33_postgres_performance_reliability"' in src


def test_private_api_route_and_configuration_contract():
    route=open('services/ai/routes/retrieval.py').read(); cfg=open('src/verideploy/config.py').read(); env=open('.env.example').read()
    assert '@router.post("/orchestrated"' in route
    assert '@router.get("/traces/{run_id}"' in route
    assert 'get_retrieval_pipeline' in route
    for x in ('retrieval_pipeline_top_k','retrieval_pipeline_max_expansions','retrieval_pipeline_min_rerank_score'): assert x in cfg
    for x in ('RETRIEVAL_PIPELINE_TOP_K','RETRIEVAL_PIPELINE_MAX_EXPANSIONS','RETRIEVAL_PIPELINE_MIN_RERANK_SCORE'): assert x in env


def test_postgres_parent_resolver_uses_canonical_chunk_content_hashes():
    src=open('src/verideploy/rag/orchestration/postgres_parent.py').read()
    assert 'retrieval_chunks' in src and 'content_hash' in src and 'ordinal' in src
    assert 'tenant_id=:tenant_id' in src
