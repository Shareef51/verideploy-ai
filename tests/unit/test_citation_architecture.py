from __future__ import annotations
import hashlib
from uuid import UUID,uuid4
import pytest

from verideploy.rag.access.schemas import PREVIEW_PERMISSION,READ_PERMISSION,RetrievalAuthorizationScope
from verideploy.rag.citations.repository import CitationSource,InMemoryCitationRepository,InMemoryCitationSourceRepository
from verideploy.rag.citations.schemas import CitationBuildRequest,PageLocator,TimecodeLocator,CodeLocator
from verideploy.rag.citations.service import CitationService,stable_citation_id
from verideploy.rag.hallucination.repository import InMemoryHallucinationProtectionRepository
from verideploy.rag.hallucination.schemas import HallucinationProtectionRequest,ProposedClaim
from verideploy.rag.hallucination.service import HallucinationProtector
from verideploy.rag.orchestration.schemas import ParentResolvedContext,PipelineCandidate,QueryAnalysis,RetrievalPipelineResult,RetrievalPipelineTrace
from verideploy.rag.retrieval.schemas import RetrievalChannel,RetrievalDocumentKind
from verideploy.rag.self_corrective.repository import InMemorySelfCorrectiveRunRepository
from verideploy.rag.self_corrective.schemas import SelfCorrectiveRAGResult,StopReason


def fixture(content="Checkout database pool exhaustion caused latency and elevated errors."):
    tenant=uuid4();chunk=uuid4();doc=uuid4();digest=hashlib.sha256(content.encode()).hexdigest();version="a"*64
    candidate=PipelineCandidate(chunk_id=chunk,document_id=doc,source_key="runbook://checkout/db-pool",title="Checkout DB Pool Runbook",content=content,document_kind=RetrievalDocumentKind.RUNBOOK,retrieval_score=.03,rerank_score=.9,final_rank=1,contributing_queries=["checkout latency"],channels=[RetrievalChannel.HYBRID],source_version=version)
    context=ParentResolvedContext(chunk_id=chunk,document_id=doc,source_key=candidate.source_key,title=candidate.title,content=content,content_sha256=digest,source_version=version,estimated_tokens=20)
    trace=RetrievalPipelineTrace(run_id=uuid4(),tenant_id=tenant,pipeline_version="1.0.0",input_sha256="c"*64,analysis=QueryAnalysis(normalized_query="checkout latency",tokens=["checkout","latency"],expansions=[],query_version="1.0.0"),retrieval_trace_ids=[],decisions=[],selected_chunk_ids=[chunk],context_sha256="d"*64)
    pipeline=RetrievalPipelineResult(candidates=[candidate],context=[context],trace=trace)
    run=SelfCorrectiveRAGResult(run_id=uuid4(),tenant_id=tenant,answerable=True,qualified=False,stop_reason=StopReason.SUFFICIENT_EVIDENCE,attempts=[],final_retrieval=pipeline,controller_version="1.0.0")
    source_runs=InMemorySelfCorrectiveRunRepository();source_runs.save(run)
    halluc_repo=InMemoryHallucinationProtectionRepository();protector=HallucinationProtector(source_runs=source_runs,repository=halluc_repo)
    verification=protector.protect(HallucinationProtectionRequest(tenant_id=tenant,self_corrective_run_id=run.run_id,claims=[ProposedClaim(claim_id="root-cause",text="Checkout database pool exhaustion caused latency",evidence_chunk_ids=(chunk,),proposed_confidence=.95)]))
    citation_repo=InMemoryCitationRepository();sources=InMemoryCitationSourceRepository([CitationSource(tenant_id=tenant,document_id=doc,chunk_id=chunk,source_key=candidate.source_key,title=candidate.title,content=content,content_hash=digest,chunk_ordinal=3,required_permission=READ_PERMISSION,service="checkout",environment="production",team="commerce",document_kind="runbook")])
    service=CitationService(hallucination_runs=halluc_repo,source_runs=source_runs,repository=citation_repo,sources=sources)
    return tenant,chunk,doc,verification,service,citation_repo


def test_stable_citation_id_and_claim_mapping_are_reproducible():
    tenant,chunk,doc,v,s,_=fixture();req=CitationBuildRequest(tenant_id=tenant,verification_id=v.verification_id)
    a=s.build_from_verification(req);b=s.build_from_verification(req)
    assert a.final_claims_cited and a.all_citations_entail and len(a.citations)==1 and len(a.mappings)==1
    assert a.citations[0].citation_id==b.citations[0].citation_id
    assert a.mappings[0].claim_id=="root-cause" and a.mappings[0].entails_released_claim
    assert a.citations[0].deep_link==f"/citations/{a.citations[0].citation_id}"


def test_page_timecode_and_code_locators_validate_and_affect_identity():
    tenant,chunk,doc,v,s,_=fixture()
    page=PageLocator(page_number=7,bbox=(10,20,90,120));time=TimecodeLocator(start_ms=1200,end_ms=4800,speaker="on-call");code=CodeLocator(path="services/checkout/pool.py",start_line=40,end_line=64,commit_sha="abcdef1")
    ids={stable_citation_id(tenant_id=tenant,document_id=doc,chunk_id=chunk,source_version="a"*64,evidence_sha256="b"*64,locator=x) for x in (page,time,code)}
    assert len(ids)==3
    with pytest.raises(ValueError):CodeLocator(path="../secret",start_line=1,end_line=2)
    with pytest.raises(ValueError):TimecodeLocator(start_ms=10,end_ms=9)


def test_locator_override_is_persisted_in_bundle():
    tenant,chunk,_,v,s,_=fixture();loc=PageLocator(page_number=2)
    b=s.build_from_verification(CitationBuildRequest(tenant_id=tenant,verification_id=v.verification_id,locators={chunk:loc}))
    assert b.citations[0].locator.kind=="page" and b.citations[0].locator.page_number==2


def test_source_hash_mismatch_fails_citation_closure():
    tenant,chunk,doc,v,original,_=fixture()
    bad_sources=InMemoryCitationSourceRepository([CitationSource(tenant_id=tenant,document_id=doc,chunk_id=chunk,source_key="runbook://bad",title="bad",content="tampered",content_hash="0"*64,chunk_ordinal=0,required_permission=READ_PERMISSION,service="checkout",environment="production",team="commerce",document_kind="runbook")])
    svc=CitationService(hallucination_runs=original.hallucination_runs,source_runs=original.source_runs,repository=InMemoryCitationRepository(),sources=bad_sources)
    with pytest.raises(ValueError,match="citation closure failed"):
        svc.build_from_verification(CitationBuildRequest(tenant_id=tenant,verification_id=v.verification_id))


def test_permission_safe_preview_requires_preview_and_source_permissions():
    tenant,_,_,v,s,_=fixture();b=s.build_from_verification(CitationBuildRequest(tenant_id=tenant,verification_id=v.verification_id));cid=b.citations[0].citation_id
    allowed=RetrievalAuthorizationScope(tenant_id=tenant,permissions=frozenset({READ_PERMISSION,PREVIEW_PERMISSION}),allowed_services=frozenset({"checkout"}),allowed_environments=frozenset({"production"}),allowed_teams=frozenset({"commerce"}),allowed_document_kinds=frozenset({"runbook"}))
    assert s.preview(tenant_id=tenant,citation_id=cid,authorization=allowed) is not None
    missing_preview=allowed.model_copy(update={"permissions":frozenset({READ_PERMISSION})})
    assert s.preview(tenant_id=tenant,citation_id=cid,authorization=missing_preview) is None
    wrong_service=allowed.model_copy(update={"allowed_services":frozenset({"ledger"})})
    assert s.preview(tenant_id=tenant,citation_id=cid,authorization=wrong_service) is None


def test_wrong_tenant_cannot_fetch_citation_or_links():
    tenant,_,_,v,s,_=fixture();b=s.build_from_verification(CitationBuildRequest(tenant_id=tenant,verification_id=v.verification_id));other=uuid4()
    assert s.get_citation(tenant_id=other,citation_id=b.citations[0].citation_id) is None
    assert s.claim_links(tenant_id=other,verification_id=v.verification_id,claim_id="root-cause")==[]


def test_migration_has_rls_append_only_and_tenant_guards():
    t=open("src/verideploy/database/migrations/versions/0020_citation_architecture.py").read()
    for token in ("citations","claim_citations","FORCE ROW LEVEL SECURITY","prevent_citation_mutation","validate_citation_source_tenant","validate_mapping_tenant","locator_kind IN ('text','page','timecode','code')"):
        assert token in t
    assert 'down_revision="0019_milestone37_hallucination_protection"' in t


def test_private_api_and_public_gateway_deep_link_contract():
    route=open("services/ai/routes/citations.py").read();app=open("apps/gateway/src/app.module.ts").read();controller=open("apps/gateway/src/citations/citations.controller.ts").read();web=open("apps/web/app/(platform)/citations/[citationId]/page.tsx").read()
    assert '@router.post("/from-verification"' in route and '@router.get("/{citation_id}/preview"' in route
    assert "CitationsModule" in app and '@Controller("citations")' in controller
    assert "/api/v1/citations/" in web and "/internal/v1" not in web


def test_gateway_does_not_trust_browser_permissions():
    svc=open("apps/gateway/src/citations/citations.service.ts").read();controller=open("apps/gateway/src/citations/citations.controller.ts").read()
    assert "GATEWAY_RETRIEVAL_PERMISSIONS" in svc
    assert 'x-retrieval-permissions' not in controller.casefold()


def test_version_contract():
    version = open("src/verideploy/__init__.py").read().strip().split('"')[1]
    major, minor, patch = (int(part) for part in version.split("."))
    assert (major, minor, patch) >= (0, 38, 0)
