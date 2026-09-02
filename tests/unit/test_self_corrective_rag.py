from __future__ import annotations

from uuid import UUID, uuid4
import pytest

from verideploy.rag.access.schemas import RequestedMetadataFilters, RetrievalAuthorizationScope
from verideploy.rag.orchestration.schemas import (
    ParentResolvedContext, PipelineCandidate, QueryAnalysis, RetrievalPipelineRequest,
    RetrievalPipelineResult, RetrievalPipelineTrace,
)
from verideploy.rag.retrieval.schemas import RetrievalChannel, RetrievalDocumentKind
from verideploy.rag.self_corrective.external import EXTERNAL_SEARCH_PERMISSION
from verideploy.rag.self_corrective.grading import grade_evidence
from verideploy.rag.self_corrective.repository import InMemorySelfCorrectiveRunRepository
from verideploy.rag.self_corrective.schemas import (
    EvidenceGrade, ExternalEvidence, ExternalSearchMode, SelfCorrectiveRAGRequest, StopReason,
)
from verideploy.rag.self_corrective.service import SelfCorrectiveRAG


def request(tenant: UUID, **updates) -> RetrievalPipelineRequest:
    data = dict(
        tenant_id=tenant, query="checkout latency", service="checkout", environment="production",
        document_kinds=[RetrievalDocumentKind.RUNBOOK], retrieval_mode=RetrievalChannel.HYBRID,
        top_k=4, candidate_k=10, max_expansions=1, max_per_source=2, min_rerank_score=.1,
        context_token_budget=2000, model_name="text-embedding-3-large", dimensions=3072,
    )
    data.update(updates)
    return RetrievalPipelineRequest(**data)


def result(tenant: UUID, *, scores=(.70, .65), sources=("runbook://a", "incident://b")) -> RetrievalPipelineResult:
    candidates=[]; contexts=[]
    for idx, score in enumerate(scores):
        chunk=uuid4(); doc=uuid4(); source=sources[min(idx,len(sources)-1)]
        candidates.append(PipelineCandidate(
            chunk_id=chunk, document_id=doc, source_key=source, title=f"evidence-{idx}",
            content="checkout database latency saturation", document_kind=RetrievalDocumentKind.RUNBOOK,
            retrieval_score=.02, rerank_score=score, final_rank=idx+1, contributing_queries=["checkout latency"],
            channels=[RetrievalChannel.HYBRID], source_version="a"*64,
        ))
        contexts.append(ParentResolvedContext(
            chunk_id=chunk, document_id=doc, source_key=source, title=f"evidence-{idx}", content="context",
            content_sha256="b"*64, source_version="a"*64, estimated_tokens=10,
        ))
    trace=RetrievalPipelineTrace(
        run_id=uuid4(), tenant_id=tenant, pipeline_version="1.0.0", input_sha256="c"*64,
        analysis=QueryAnalysis(normalized_query="checkout latency", tokens=["checkout","latency"], expansions=[], query_version="1.0.0"),
        retrieval_trace_ids=[], decisions=[], selected_chunk_ids=[x.chunk_id for x in candidates], context_sha256="d"*64,
        metadata={},
    )
    return RetrievalPipelineResult(candidates=candidates, context=contexts, trace=trace)


class FakePipeline:
    def __init__(self, results): self.results=list(results); self.requests=[]; self.auth=[]
    async def run(self, req, *, authorization=None):
        self.requests.append(req.model_copy(deep=True)); self.auth.append(authorization)
        if self.results: return self.results.pop(0)
        raise AssertionError("unexpected retry")


class FakeExternal:
    async def search(self, *, query: str, max_results: int):
        return [ExternalEvidence(source="public",title="External status",content="supplemental",locator="https://example.invalid/status")]


def auth(tenant, *, services=frozenset({"checkout"}), permissions=frozenset({"retrieval.read"})):
    return RetrievalAuthorizationScope(
        tenant_id=tenant, permissions=permissions, allowed_services=services,
        allowed_environments=frozenset({"production"}), allowed_teams=frozenset({"commerce"}),
        allowed_document_kinds=frozenset({"runbook","historical_incident"}),
    )


def test_evidence_grader_has_transparent_sufficient_and_insufficient_thresholds():
    tenant=uuid4()
    strong=grade_evidence(result(tenant))
    weak=grade_evidence(result(tenant,scores=(.20,),sources=("one",)))
    assert strong.grade is EvidenceGrade.SUFFICIENT and strong.source_count==2 and strong.score>=.60
    assert weak.grade in {EvidenceGrade.WEAK,EvidenceGrade.INSUFFICIENT}
    assert "insufficient_source_corroboration" in weak.reasons


@pytest.mark.asyncio
async def test_sufficient_evidence_stops_after_first_attempt():
    tenant=uuid4(); pipeline=FakePipeline([result(tenant)]); repo=InMemorySelfCorrectiveRunRepository()
    out=await SelfCorrectiveRAG(pipeline=pipeline,repository=repo).run(SelfCorrectiveRAGRequest(retrieval=request(tenant)),authorization=auth(tenant))
    assert out.answerable and not out.qualified and out.stop_reason is StopReason.SUFFICIENT_EVIDENCE
    assert len(out.attempts)==1 and len(pipeline.requests)==1
    assert repo.get(tenant_id=tenant,run_id=out.run_id) is not None


@pytest.mark.asyncio
async def test_insufficient_evidence_is_qualified_and_bounded_not_fabricated():
    tenant=uuid4(); empty=result(tenant,scores=(),sources=())
    pipeline=FakePipeline([empty,empty,empty]); out=await SelfCorrectiveRAG(pipeline=pipeline,repository=InMemorySelfCorrectiveRunRepository()).run(
        SelfCorrectiveRAGRequest(retrieval=request(tenant),max_attempts=3,max_query_rewrites=2), authorization=auth(tenant)
    )
    assert not out.answerable and out.qualified and out.qualification
    assert len(out.attempts)<=3 and len(pipeline.requests)<=3
    assert out.external_evidence==[]
    assert out.stop_reason in {StopReason.EXTERNAL_SEARCH_DISABLED,StopReason.RETRY_BUDGET_EXHAUSTED,StopReason.NO_PROGRESS}


@pytest.mark.asyncio
async def test_query_rewrite_is_deterministic_and_bounded():
    tenant=uuid4(); empty=result(tenant,scores=(),sources=())
    pipeline=FakePipeline([empty,empty]);
    await SelfCorrectiveRAG(pipeline=pipeline,repository=InMemorySelfCorrectiveRunRepository()).run(
        SelfCorrectiveRAGRequest(retrieval=request(tenant),max_attempts=2,max_query_rewrites=1),authorization=auth(tenant)
    )
    assert len(pipeline.requests)==2
    assert pipeline.requests[1].query != pipeline.requests[0].query
    assert "incident" in pipeline.requests[1].query.casefold()


@pytest.mark.asyncio
async def test_requested_scope_relaxation_never_changes_trusted_authorization():
    tenant=uuid4(); empty=result(tenant,scores=(),sources=())
    pipeline=FakePipeline([empty,empty,empty])
    narrow=request(tenant,metadata_filters=RequestedMetadataFilters(services=["checkout"],severities=["sev1"]),service=None,environment=None,document_kinds=[])
    await SelfCorrectiveRAG(pipeline=pipeline,repository=InMemorySelfCorrectiveRunRepository()).run(
        SelfCorrectiveRAGRequest(retrieval=narrow,max_attempts=3,max_query_rewrites=1,allow_requested_scope_relaxation=True),authorization=auth(tenant)
    )
    assert all(a.allowed_services==frozenset({"checkout"}) for a in pipeline.auth)
    assert any(r.metadata_filters is not None and not r.metadata_filters.services and not r.metadata_filters.severities for r in pipeline.requests[1:])


@pytest.mark.asyncio
async def test_contradictory_legacy_and_structured_scope_fails_closed_before_broadening():
    tenant=uuid4(); empty=result(tenant,scores=(),sources=())
    pipeline=FakePipeline([empty])
    req=request(tenant,service="checkout",metadata_filters=RequestedMetadataFilters(services=["ledger"]))
    out=await SelfCorrectiveRAG(pipeline=pipeline,repository=InMemorySelfCorrectiveRunRepository()).run(
        SelfCorrectiveRAGRequest(retrieval=req,max_attempts=1),authorization=auth(tenant)
    )
    assert out.stop_reason is StopReason.AUTHORIZATION_EMPTY
    assert len(pipeline.requests)==1 and out.qualified


@pytest.mark.asyncio
async def test_external_search_is_policy_and_permission_gated():
    tenant=uuid4(); empty=result(tenant,scores=(),sources=())
    controller=SelfCorrectiveRAG(pipeline=FakePipeline([empty]),repository=InMemorySelfCorrectiveRunRepository(),external_search=FakeExternal())
    denied=await controller.run(SelfCorrectiveRAGRequest(retrieval=request(tenant),max_attempts=1,external_search_mode=ExternalSearchMode.AUTHORIZED_ONLY),authorization=auth(tenant))
    assert denied.stop_reason is StopReason.EXTERNAL_SEARCH_UNAUTHORIZED and denied.external_evidence==[]
    allowed_auth=auth(tenant,permissions=frozenset({"retrieval.read",EXTERNAL_SEARCH_PERMISSION}))
    controller2=SelfCorrectiveRAG(pipeline=FakePipeline([empty]),repository=InMemorySelfCorrectiveRunRepository(),external_search=FakeExternal())
    allowed=await controller2.run(SelfCorrectiveRAGRequest(retrieval=request(tenant),max_attempts=1,external_search_mode=ExternalSearchMode.AUTHORIZED_ONLY),authorization=allowed_auth)
    assert len(allowed.external_evidence)==1 and allowed.qualified


def test_in_memory_repository_defends_saved_history_from_mutation():
    # Save/get deep-copy contract is independently tested without executing the controller.
    tenant=uuid4(); repo=InMemorySelfCorrectiveRunRepository(); base=result(tenant)
    from verideploy.rag.self_corrective.schemas import SelfCorrectiveRAGResult
    saved=SelfCorrectiveRAGResult(run_id=uuid4(),tenant_id=tenant,answerable=True,qualified=False,stop_reason=StopReason.SUFFICIENT_EVIDENCE,attempts=[],final_retrieval=base,controller_version="1.0.0")
    repo.save(saved); saved.final_retrieval.trace.metadata["tampered"]=True
    assert "tampered" not in repo.get(tenant_id=tenant,run_id=saved.run_id).final_retrieval.trace.metadata


def test_migration_rls_append_only_and_attempt_tenant_guard():
    text=open('src/verideploy/database/migrations/versions/0018_self_corrective_rag.py').read()
    for token in ('self_corrective_rag_runs','self_corrective_rag_attempts','FORCE ROW LEVEL SECURITY','prevent_self_corrective_rag_mutation','validate_attempt_tenant','attempt_number','evidence_score'):
        assert token in text
    assert 'down_revision = "0017_milestone35_metadata_filtering_authorization"' in text


def test_api_and_config_contract():
    route=open('services/ai/routes/retrieval.py').read(); cfg=open('src/verideploy/config.py').read(); env=open('.env.example').read()
    assert '@router.post("/self-corrective"' in route and '@router.get("/self-corrective/{run_id}"' in route
    for token in ('self_corrective_rag_max_attempts','self_corrective_rag_max_query_rewrites','self_corrective_rag_allow_scope_relaxation','self_corrective_rag_external_search_mode'):
        assert token in cfg
    for token in ('SELF_CORRECTIVE_RAG_MAX_ATTEMPTS','SELF_CORRECTIVE_RAG_MAX_QUERY_REWRITES','SELF_CORRECTIVE_RAG_ALLOW_SCOPE_RELAXATION','SELF_CORRECTIVE_RAG_EXTERNAL_SEARCH_MODE'):
        assert token in env
