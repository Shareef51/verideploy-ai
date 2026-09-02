from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.ai.agents import get_critic_agent
from services.ai.main import app
from verideploy.agents.contracts import AgentAuthorization, AgentPlan, AgentRequest, SupervisorDecision, ToolBudget, ToolPermission
from verideploy.agents.critic import ClaimVerdict, CriticAgent
from verideploy.agents.prompts import build_prompt_registry
from verideploy.agents.rca import (
    RCAAgentResult, RCAHypothesisAssessment, RCAHypothesisKind, RCASufficiency,
)
from verideploy.agents.repository import InMemoryAgentRunRepository
from verideploy.rag.fusion.schemas import EvidenceChannel, EvidenceLocator, NormalizedEvidence


class DummyModel: pass


def req(tenant=None):
    return AgentRequest(
        tenant_id=tenant or uuid4(), user_id="sre-24", correlation_id="corr-24",
        objective="Critique the checkout RCA", context={"service":"checkout","environment":"production"},
    )


def auth(r, ok=True):
    perms={ToolPermission.CRITIC_ANALYSIS_READ} if ok else set()
    return AgentAuthorization(tenant_id=r.tenant_id,user_id=r.user_id,allowed_permissions=frozenset(perms))


def ev(r, content, *, channel=EvidenceChannel.RUNTIME, minute=0, title="evidence"):
    eid=uuid4()
    return NormalizedEvidence(
        evidence_id=eid, tenant_id=r.tenant_id, channel=channel, source_system="test", source_id=str(eid),
        source_key=f"src:{eid}", title=title, content=content,
        content_hash=("a" if channel is EvidenceChannel.RUNTIME else "b")*64,
        relevance_score=.95, source_confidence=.95, fusion_score=.95,
        locator=EvidenceLocator(timestamp=datetime(2026,8,17,14,minute,tzinfo=timezone.utc)), estimated_tokens=20,
        provenance={"service":"checkout","environment":"production"},
    )


def rca_result(a, b, *, statement="Database connection pool exhaustion caused checkout latency", disconfirm=None, adjusted=.9, determined=True):
    assessment=RCAHypothesisAssessment(
        hypothesis_id="hyp-01",rank=1,kind=RCAHypothesisKind.ROOT_CAUSE,statement=statement,
        model_confidence=.95,adjusted_confidence=adjusted,support_count=2,contradiction_count=1 if disconfirm else 0,
        supporting_channels=sorted({a.channel,b.channel},key=lambda x:x.value),temporal_score=1,causal_score=1,
        supporting_evidence_ids=[a.evidence_id,b.evidence_id],disconfirming_evidence_ids=[disconfirm.evidence_id] if disconfirm else [],
        causal_links=[],temporal_rationale="aligned",recommended_tests=[])
    return RCAAgentResult(
        incident_summary="checkout latency incident",hypotheses=[assessment],root_causes=[assessment],triggers=[],alternatives=[],limitations=[],
        sufficiency=RCASufficiency(root_cause_determined=determined,top_hypothesis_id="hyp-01" if determined else None,evidence_count=2+(1 if disconfirm else 0),evidence_channels=assessment.supporting_channels,reason_codes=["sufficient"] if determined else ["insufficient"]),tool_calls_used=0)


def agent(followup=None, repo=None):
    return CriticAgent(model=DummyModel(),prompts=build_prompt_registry(),repository=repo or InMemoryAgentRunRepository(),followup=followup)


@pytest.mark.asyncio
async def test_supported_rca_passes_with_entailment_and_no_escalation():
    r=req(); a=ev(r,"database connection pool reached maximum and exhausted available connections"); b=ev(r,"runbook says connection pool exhaustion causes checkout latency and queueing",channel=EvidenceChannel.TEXT)
    result=await agent().run(r,authorization=auth(r),rca=rca_result(a,b),evidence=[a,b],budget=ToolBudget(max_calls=0),model_name="m",dimensions=3,candidate_k=4)
    assert result.passed is True
    assert result.claims[0].verdict is ClaimVerdict.ENTAILED
    assert result.adjusted_root_cause_confidence >= .55
    assert result.human_escalation.required is False


@pytest.mark.asyncio
async def test_hallucinated_rca_cannot_pass():
    r=req(); a=ev(r,"redis cache hit rate remained stable"); b=ev(r,"tls certificate valid for another 90 days",channel=EvidenceChannel.TEXT)
    result=await agent().run(r,authorization=auth(r),rca=rca_result(a,b,statement="Kernel memory corruption caused checkout latency"),evidence=[a,b],budget=ToolBudget(max_calls=0),model_name="m",dimensions=3,candidate_k=4)
    assert result.passed is False
    assert result.hallucinated_claim_count==1
    assert result.claims[0].verdict is ClaimVerdict.UNSUPPORTED
    assert "unsupported_rca_claim" in result.human_escalation.reason_codes


@pytest.mark.asyncio
async def test_disconfirming_evidence_forces_contradiction_and_escalation():
    r=req(); a=ev(r,"database connection pool reached maximum"); b=ev(r,"connection pool exhaustion causes checkout latency",channel=EvidenceChannel.TEXT); d=ev(r,"database connection pool remained healthy and below 40 percent")
    result=await agent().run(r,authorization=auth(r),rca=rca_result(a,b,disconfirm=d),evidence=[a,b,d],budget=ToolBudget(max_calls=0),model_name="m",dimensions=3,candidate_k=4)
    assert result.passed is False and result.contradicted_claim_count==1
    assert result.claims[0].verdict is ClaimVerdict.CONTRADICTED
    assert "contradictory_rca_claim" in result.human_escalation.reason_codes


class Followup:
    def __init__(self, items): self.items=items; self.calls=[]
    async def retrieve(self, **kwargs): self.calls.append(kwargs); return self.items


@pytest.mark.asyncio
async def test_bounded_followup_can_recover_unsupported_claim():
    r=req(); a=ev(r,"request failures increased"); b=ev(r,"unrelated change record",channel=EvidenceChannel.TEXT)
    extra=ev(r,"database connection pool exhaustion caused checkout latency during the incident",channel=EvidenceChannel.TEXT)
    f=Followup([extra])
    result=await agent(f).run(r,authorization=auth(r),rca=rca_result(a,b),evidence=[a,b],budget=ToolBudget(max_calls=1),max_followups=1,model_name="m",dimensions=3,candidate_k=4)
    assert len(f.calls)==1 and result.tool_calls_used==1
    assert result.claims[0].followup_used is True
    assert result.claims[0].verdict is ClaimVerdict.ENTAILED
    assert extra.evidence_id in result.claims[0].entailing_evidence_ids


@pytest.mark.asyncio
async def test_followup_is_bounded_by_budget_before_network_call():
    r=req(); a=ev(r,"unrelated"); b=ev(r,"also unrelated",channel=EvidenceChannel.TEXT); f=Followup([])
    with pytest.raises(ValueError,match="exceeds tool budget"):
        await agent(f).run(r,authorization=auth(r),rca=rca_result(a,b),evidence=[a,b],budget=ToolBudget(max_calls=0),max_followups=1,model_name="m",dimensions=3,candidate_k=4)
    assert f.calls==[]


@pytest.mark.asyncio
async def test_followup_failure_to_entail_requires_human_escalation():
    r=req(); a=ev(r,"unrelated"); b=ev(r,"also unrelated",channel=EvidenceChannel.TEXT); f=Followup([ev(r,"still unrelated",channel=EvidenceChannel.TEXT)])
    result=await agent(f).run(r,authorization=auth(r),rca=rca_result(a,b),evidence=[a,b],budget=ToolBudget(max_calls=1),max_followups=1,model_name="m",dimensions=3,candidate_k=4)
    assert result.passed is False
    assert "followup_retrieval_insufficient" in result.human_escalation.reason_codes


@pytest.mark.asyncio
async def test_unknown_rca_evidence_reference_is_rejected_and_run_failed():
    r=req(); a=ev(r,"database pool exhausted"); b=ev(r,"pool exhaustion causes latency",channel=EvidenceChannel.TEXT); rca=rca_result(a,b)
    rca.hypotheses[0].supporting_evidence_ids[1]=uuid4()
    repo=InMemoryAgentRunRepository()
    with pytest.raises(ValueError,match="unknown evidence"):
        await agent(repo=repo).run(r,authorization=auth(r),rca=rca,evidence=[a,b],budget=ToolBudget(max_calls=0),model_name="m",dimensions=3,candidate_k=4)
    assert list(repo.records.values())[0].status.value=="FAILED"


@pytest.mark.asyncio
async def test_permission_tenant_and_trusted_scope_enforced_before_critique():
    r=req(); a=ev(r,"database pool exhausted"); b=ev(r,"pool exhaustion causes latency",channel=EvidenceChannel.TEXT); crit=agent()
    with pytest.raises(PermissionError):
        await crit.run(r,authorization=auth(r,False),rca=rca_result(a,b),evidence=[a,b],budget=ToolBudget(max_calls=0),model_name="m",dimensions=3,candidate_k=4)
    wrong=a.model_copy(update={"tenant_id":uuid4()})
    with pytest.raises(PermissionError,match="tenant"):
        await crit.run(r,authorization=auth(r),rca=rca_result(a,b),evidence=[wrong,b],budget=ToolBudget(max_calls=0),model_name="m",dimensions=3,candidate_k=4)
    wrong_scope=b.model_copy(update={"provenance":{"service":"payments","environment":"production"}})
    with pytest.raises(PermissionError,match="service"):
        await crit.run(r,authorization=auth(r),rca=rca_result(a,b),evidence=[a,wrong_scope],budget=ToolBudget(max_calls=0),model_name="m",dimensions=3,candidate_k=4)


def test_supervisor_planner_and_prompt_versions_include_critic():
    SupervisorDecision.model_validate({"route":"critic","rationale":"validate RCA","confidence":.9,"required_permissions":["critic.analysis.read"]})
    with pytest.raises(ValidationError,match="critic.analysis.read"):
        SupervisorDecision.model_validate({"route":"critic","rationale":"validate RCA","confidence":.9,"required_permissions":[]})
    AgentPlan.model_validate({"rationale":"RCA then critic","steps":[
        {"step_id":"step-01","agent":"rca","objective":"rank causes","required_permissions":["rca.analysis.read"],"max_tool_calls":0,"depends_on":[]},
        {"step_id":"step-02","agent":"critic","objective":"challenge RCA","required_permissions":["critic.analysis.read"],"max_tool_calls":2,"depends_on":["step-01"]},
    ]})
    reg=build_prompt_registry(); assert reg.get("critic","1.0.0").sha256; assert reg.get("supervisor","1.5.0").sha256; assert reg.get("planner","1.5.0").sha256


@pytest.mark.asyncio
async def test_completed_critic_run_persists_prompt_input_hash_and_budget():
    r=req(); a=ev(r,"database connection pool reached maximum"); b=ev(r,"connection pool exhaustion causes checkout latency",channel=EvidenceChannel.TEXT); repo=InMemoryAgentRunRepository()
    result=await agent(repo=repo).run(r,authorization=auth(r),rca=rca_result(a,b),evidence=[a,b],budget=ToolBudget(max_calls=0),model_name="m",dimensions=3,candidate_k=4)
    record=list(repo.records.values())[0]
    assert record.status.value=="COMPLETED" and record.prompt_name=="critic" and record.prompt_version=="1.0.0"
    assert len(record.prompt_sha256)==64 and len(record.input_sha256)==64 and record.tool_calls_used==0 and result.passed


def test_private_critic_endpoint_enforces_service_tenant_and_user_scope():
    r=req(); a=ev(r,"database connection pool reached maximum"); b=ev(r,"connection pool exhaustion causes checkout latency",channel=EvidenceChannel.TEXT); rr=rca_result(a,b)
    class Stub:
        async def run(self,*args,**kwargs):
            kwargs.update(model_name="m",dimensions=3,candidate_k=4)
            return await agent().run(*args,**kwargs)
    app.dependency_overrides[get_critic_agent]=lambda: Stub()
    payload={"request":r.model_dump(mode="json"),"permissions":["critic.analysis.read"],"rca":rr.model_dump(mode="json"),"evidence":[a.model_dump(mode="json"),b.model_dump(mode="json")]}
    headers={"x-internal-service":"bad","x-tenant-id":str(r.tenant_id),"x-user-id":r.user_id}
    try:
        with TestClient(app) as client:
            assert client.post("/internal/v1/agents/critic",json=payload,headers=headers).status_code==401
            headers["x-internal-service"]="verideploy-gateway"; headers["x-tenant-id"]=str(uuid4())
            assert client.post("/internal/v1/agents/critic",json=payload,headers=headers).status_code==403
            headers["x-tenant-id"]=str(r.tenant_id); headers["x-user-id"]="other"
            assert client.post("/internal/v1/agents/critic",json=payload,headers=headers).status_code==403
            headers["x-user-id"]=r.user_id
            response=client.post("/internal/v1/agents/critic",json=payload,headers=headers)
            assert response.status_code==200 and response.json()["passed"] is True
    finally:
        app.dependency_overrides.pop(get_critic_agent,None)


def test_critic_config_rejects_followup_budget_and_threshold_misconfiguration(monkeypatch):
    from verideploy.config import Settings
    with pytest.raises(ValidationError,match="CRITIC_MAX_FOLLOWUPS"):
        Settings(critic_agent_tool_budget=1,critic_max_followups=2)
    with pytest.raises(ValidationError,match="CRITIC_PARTIAL_ENTAILMENT_THRESHOLD"):
        Settings(critic_entailment_threshold=.1,critic_partial_entailment_threshold=.2)
