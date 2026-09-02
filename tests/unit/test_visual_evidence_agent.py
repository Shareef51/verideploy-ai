from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from verideploy.agents.contracts import AgentAuthorization, AgentRequest, ToolBudget, ToolPermission
from verideploy.agents.prompts import build_prompt_registry
from verideploy.agents.repository import InMemoryAgentRunRepository
from verideploy.agents.visual import VisualEvidenceAgent, VisualQueryAnalysis
from verideploy.multimodal.image_intelligence import (
    ArchitectureAnalysisResult,
    DashboardAnalysisResult,
    EvidenceLocator,
    ImageAnalysisType,
    ImageDetail,
    ImageProvenance,
    VisualObservation,
)
from verideploy.rag.visual_retrieval.schemas import (
    VisualBackend,
    VisualSearchHit,
    VisualSearchResult,
)


class FakeModel:
    def __init__(self, output): self.output=output; self.calls=[]
    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs["output_model"].model_validate(self.output)


class FakeSearch:
    def __init__(self, hits): self.hits=hits; self.calls=[]
    async def search(self, query):
        self.calls.append(query)
        return VisualSearchResult(backend=VisualBackend.CPU_FALLBACK, model_name="cpu", hits=self.hits)


class FakeAnalyzer:
    def __init__(self, result_factory=None, *, fail=False, tenant_override=None, width=1600, height=1000):
        self.calls=[]; self.result_factory=result_factory; self.fail=fail; self.tenant_override=tenant_override; self.width=width; self.height=height
    async def analyze(self, *, tenant_id, correlation_id, hit, analysis_type):
        self.calls.append((tenant_id, hit, analysis_type))
        if self.fail: raise RuntimeError("provider unavailable")
        image_id=uuid4()
        provenance=ImageProvenance(
            image_id=image_id, tenant_id=self.tenant_override or tenant_id, source_type="document_page",
            source_object_ref=hit.image_path, original_sha256=hit.image_sha256, prepared_sha256="b"*64,
            mime_type="image/png", width=self.width, height=self.height, page_number=hit.page_number, detail=ImageDetail.HIGH,
        )
        if self.result_factory:
            result=self.result_factory(image_id)
        elif analysis_type is ImageAnalysisType.ARCHITECTURE:
            result=ArchitectureAnalysisResult(
                image_id=image_id, summary="checkout connects to Redis",
                observations=[VisualObservation(observation_id="obs-1", image_id=image_id, statement="checkout box connects to Redis box", confidence=.91, locator=EvidenceLocator(x_min=.1,y_min=.1,x_max=.8,y_max=.7))],
                components=[], relationships=[], limitations=[])
        else:
            result=DashboardAnalysisResult(
                image_id=image_id, summary="latency panel elevated",
                observations=[VisualObservation(observation_id="obs-1", image_id=image_id, statement="p95 latency line rises", confidence=.88, locator=EvidenceLocator(x_min=.2,y_min=.2,x_max=.9,y_max=.8))],
                anomalies=[], limitations=[])
        return provenance,result


def req(context=None):
    return AgentRequest(tenant_id=uuid4(),user_id="analyst",correlation_id="corr-21",objective="Inspect checkout architecture diagram",context=context or {})

def auth(r, allowed=True):
    perms={ToolPermission.VISUAL_EVIDENCE_READ} if allowed else set()
    return AgentAuthorization(tenant_id=r.tenant_id,user_id=r.user_id,allowed_permissions=frozenset(perms))

def analysis(**updates):
    value={"normalized_query":"checkout Redis architecture diagram","intent":"architecture","analysis_type":"architecture","top_k":2,"document_id":None,"rationale":"visual topology is required"}
    value.update(updates); return value

def hit(page=1):
    return VisualSearchHit(page_id=uuid4(),document_id=uuid4(),page_number=page,score=.9,backend=VisualBackend.CPU_FALLBACK,model_name="cpu",image_path=f"/tmp/page-{page}.png",image_sha256=(f"{page:x}"*64)[:64])


def test_visual_query_contract_rejects_intent_analysis_mismatch():
    with pytest.raises(ValidationError, match="matching analysis_type"):
        VisualQueryAnalysis.model_validate(analysis(analysis_type="dashboard"))


@pytest.mark.asyncio
async def test_permission_is_required_before_model_or_tools():
    r=req(); model=FakeModel(analysis()); search=FakeSearch([hit()]); analyzer=FakeAnalyzer()
    agent=VisualEvidenceAgent(model=model,prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=search,analyzer=analyzer)
    with pytest.raises(PermissionError):
        await agent.run(r,authorization=auth(r,False),budget=ToolBudget(max_calls=2))
    assert model.calls==[] and search.calls==[] and analyzer.calls==[]


@pytest.mark.asyncio
async def test_architecture_search_analysis_evidence_locator_and_confidence():
    r=req(); h=hit(); repo=InMemoryAgentRunRepository()
    agent=VisualEvidenceAgent(model=FakeModel(analysis()),prompts=build_prompt_registry(),repository=repo,search=FakeSearch([h]),analyzer=FakeAnalyzer())
    result=await agent.run(r,authorization=auth(r),budget=ToolBudget(max_calls=3),min_short_side=720,min_confidence=.55,max_analyses=2)
    assert result.tool_calls_used==2 and result.sufficiency.sufficient is True
    item=result.evidence[0]
    assert item.analysis_type is ImageAnalysisType.ARCHITECTURE
    assert item.observations[0].locator is not None and item.confidence_level=="high"
    assert next(iter(repo.records.values())).status.value=="COMPLETED"


@pytest.mark.asyncio
async def test_dashboard_analysis_uses_dashboard_contract():
    r=req(); model=FakeModel(analysis(intent="dashboard",analysis_type="dashboard",normalized_query="checkout latency dashboard"))
    analyzer=FakeAnalyzer()
    result=await VisualEvidenceAgent(model=model,prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=FakeSearch([hit()]),analyzer=analyzer).run(r,authorization=auth(r),budget=ToolBudget(max_calls=2),max_analyses=1)
    assert analyzer.calls[0][2] is ImageAnalysisType.DASHBOARD
    assert result.evidence[0].analysis_type is ImageAnalysisType.DASHBOARD


@pytest.mark.asyncio
async def test_missing_visual_evidence_is_explicit_and_does_not_call_analyzer():
    r=req(); analyzer=FakeAnalyzer()
    result=await VisualEvidenceAgent(model=FakeModel(analysis()),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=FakeSearch([]),analyzer=analyzer).run(r,authorization=auth(r),budget=ToolBudget(max_calls=2))
    assert analyzer.calls==[]
    assert result.sufficiency.sufficient is False
    assert "no_visual_evidence" in result.sufficiency.reason_codes


@pytest.mark.asyncio
async def test_low_resolution_is_qualified_not_silently_accepted():
    r=req(); analyzer=FakeAnalyzer(width=640,height=480)
    result=await VisualEvidenceAgent(model=FakeModel(analysis(top_k=1)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=FakeSearch([hit()]),analyzer=analyzer).run(r,authorization=auth(r),budget=ToolBudget(max_calls=2),min_short_side=720,max_analyses=1)
    assert result.sufficiency.sufficient is False
    assert "low_resolution" in result.sufficiency.reason_codes
    assert result.evidence[0].confidence_level=="low"


@pytest.mark.asyncio
async def test_missing_locator_is_explicitly_insufficient():
    def result_factory(image_id):
        return ArchitectureAnalysisResult(image_id=image_id,summary="diagram",observations=[VisualObservation(observation_id="o",image_id=image_id,statement="service box",confidence=.9)],components=[],relationships=[],limitations=[])
    r=req(); analyzer=FakeAnalyzer(result_factory=result_factory)
    result=await VisualEvidenceAgent(model=FakeModel(analysis(top_k=1)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=FakeSearch([hit()]),analyzer=analyzer).run(r,authorization=auth(r),budget=ToolBudget(max_calls=2),max_analyses=1)
    assert "missing_evidence_locators" in result.sufficiency.reason_codes


@pytest.mark.asyncio
async def test_failed_visual_analysis_degrades_to_explicit_unavailable():
    r=req(); analyzer=FakeAnalyzer(fail=True)
    result=await VisualEvidenceAgent(model=FakeModel(analysis(top_k=1)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=FakeSearch([hit()]),analyzer=analyzer).run(r,authorization=auth(r),budget=ToolBudget(max_calls=2),max_analyses=1)
    assert result.evidence==[]
    assert "visual_analysis_unavailable" in result.sufficiency.reason_codes


@pytest.mark.asyncio
async def test_cross_tenant_analysis_provenance_is_rejected():
    r=req(); analyzer=FakeAnalyzer(tenant_override=uuid4())
    agent=VisualEvidenceAgent(model=FakeModel(analysis(top_k=1)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=FakeSearch([hit()]),analyzer=analyzer)
    with pytest.raises(PermissionError, match="tenant mismatch"):
        await agent.run(r,authorization=auth(r),budget=ToolBudget(max_calls=2),max_analyses=1)


@pytest.mark.asyncio
async def test_trusted_document_scope_cannot_be_broadened_and_omission_inherits_scope():
    document_id=uuid4(); r=req({"document_id":str(document_id)})
    search=FakeSearch([])
    agent=VisualEvidenceAgent(model=FakeModel(analysis(document_id=None)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=search,analyzer=FakeAnalyzer())
    await agent.run(r,authorization=auth(r),budget=ToolBudget(max_calls=2))
    assert search.calls[0].document_id==document_id
    bad=VisualEvidenceAgent(model=FakeModel(analysis(document_id=str(uuid4()))),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=FakeSearch([]),analyzer=FakeAnalyzer())
    with pytest.raises(PermissionError, match="cannot broaden"):
        await bad.run(r,authorization=auth(r),budget=ToolBudget(max_calls=2))


def test_prompt_versions_and_contract_extensions():
    from verideploy.agents.contracts import AgentPlan, PlanStep, SupervisorDecision
    registry=build_prompt_registry()
    assert len(registry.get("visual_evidence","1.0.0").sha256)==64
    assert len(registry.get("supervisor","1.2.0").sha256)==64
    decision=SupervisorDecision(route="visual_evidence",rationale="diagram required",confidence=.9,required_permissions=["visual.evidence.read"])
    plan=AgentPlan(rationale="inspect diagram",steps=[PlanStep(step_id="step-01",agent="visual_evidence",objective="inspect dashboard",required_permissions=["visual.evidence.read"],max_tool_calls=2)])
    assert decision.required_permissions==[ToolPermission.VISUAL_EVIDENCE_READ]
    assert plan.steps[0].agent=="visual_evidence"

@pytest.mark.asyncio
async def test_architecture_components_and_relationships_preserve_observation_links():
    from verideploy.multimodal.image_intelligence import ArchitectureComponent, ArchitectureRelationship
    def result_factory(image_id):
        return ArchitectureAnalysisResult(
            image_id=image_id, summary="topology",
            observations=[VisualObservation(observation_id="obs-arch",image_id=image_id,statement="checkout arrow points to Redis",confidence=.92,locator=EvidenceLocator(x_min=.1,y_min=.1,x_max=.9,y_max=.8))],
            components=[ArchitectureComponent(name="checkout",component_type="service",based_on_observation_ids=["obs-arch"])],
            relationships=[ArchitectureRelationship(source="checkout",target="Redis",relationship="connects_to",based_on_observation_ids=["obs-arch"])],
            limitations=[])
    r=req(); result=await VisualEvidenceAgent(model=FakeModel(analysis(top_k=1)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),search=FakeSearch([hit()]),analyzer=FakeAnalyzer(result_factory=result_factory)).run(r,authorization=auth(r),budget=ToolBudget(max_calls=2),max_analyses=1)
    kinds={item.kind for item in result.evidence[0].derived_findings}
    assert {"architecture_component","architecture_relationship"} <= kinds
    assert all("obs-arch" in item.based_on_observation_ids for item in result.evidence[0].derived_findings)


def test_visual_agent_private_route_enforces_trusted_service_and_tenant():
    from fastapi.testclient import TestClient
    from services.ai.main import app
    from services.ai.agents import get_visual_evidence_agent

    r=req(); expected_analysis=VisualQueryAnalysis.model_validate(analysis())
    from verideploy.agents.visual import VisualEvidenceAgentResult, VisualEvidenceSufficiency
    expected=VisualEvidenceAgentResult(analysis=expected_analysis,evidence=[],sufficiency=VisualEvidenceSufficiency(sufficient=False,evidence_count=0,direct_observation_count=0,located_observation_count=0,reason_codes=["no_visual_evidence"]),tool_calls_used=1)
    class RouteFake:
        async def run(self,*args,**kwargs): return expected
    app.dependency_overrides[get_visual_evidence_agent]=lambda:RouteFake()
    try:
        client=TestClient(app)
        payload={"request":r.model_dump(mode="json"),"permissions":["visual.evidence.read"]}
        headers={"x-internal-service":"unknown","x-tenant-id":str(r.tenant_id),"x-user-id":r.user_id}
        assert client.post("/internal/v1/agents/visual-evidence",json=payload,headers=headers).status_code==401
        headers["x-internal-service"]="verideploy-gateway"; headers["x-tenant-id"]=str(uuid4())
        assert client.post("/internal/v1/agents/visual-evidence",json=payload,headers=headers).status_code==403
        headers["x-tenant-id"]=str(r.tenant_id)
        response=client.post("/internal/v1/agents/visual-evidence",json=payload,headers=headers)
        assert response.status_code==200 and response.json()["sufficiency"]["reason_codes"]==["no_visual_evidence"]
    finally:
        app.dependency_overrides.pop(get_visual_evidence_agent,None)

@pytest.mark.asyncio
async def test_stored_visual_tool_rejects_sha_mismatch_before_image_service(tmp_path):
    from verideploy.agents.visual_tools import StoredVisualAnalysisTool
    path=tmp_path/"page.png"; path.write_bytes(b"not-the-indexed-bytes")
    h=hit(); h=h.model_copy(update={"image_path":str(path),"image_sha256":"a"*64})
    class Service:
        async def analyze(self,**kwargs): raise AssertionError("service must not be called")
    with pytest.raises(ValueError,match="SHA-256 mismatch"):
        await StoredVisualAnalysisTool(Service()).analyze(tenant_id=uuid4(),correlation_id="c",hit=h,analysis_type=ImageAnalysisType.ARCHITECTURE)


@pytest.mark.asyncio
async def test_stored_visual_tool_refuses_missing_or_remote_like_path_before_provider():
    from verideploy.agents.visual_tools import StoredVisualAnalysisTool
    h=hit().model_copy(update={"image_path":"https://attacker.invalid/page.png"})
    class Service:
        async def analyze(self,**kwargs): raise AssertionError("service must not be called")
    with pytest.raises(FileNotFoundError,match="unavailable"):
        await StoredVisualAnalysisTool(Service()).analyze(tenant_id=uuid4(),correlation_id="c",hit=h,analysis_type=ImageAnalysisType.ARCHITECTURE)
