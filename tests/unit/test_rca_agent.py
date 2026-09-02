from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.ai.agents import get_rca_agent
from services.ai.main import app
from verideploy.agents.contracts import (
    AgentAuthorization,
    AgentPlan,
    AgentRequest,
    PlanStep,
    SupervisorDecision,
    ToolPermission,
)
from verideploy.agents.prompts import build_prompt_registry
from verideploy.agents.rca import RCAAgent, RCAProposal
from verideploy.agents.repository import InMemoryAgentRunRepository
from verideploy.rag.fusion.schemas import EvidenceChannel, EvidenceLocator, NormalizedEvidence


class FakeModel:
    def __init__(self, output): self.output=output; self.calls=[]
    async def generate(self, **kwargs): self.calls.append(kwargs); return kwargs['output_model'].model_validate(self.output)


def ev(tenant, channel, title, content, *, minute=0, relevance=.9, confidence=.95, service='checkout', environment='production'):
    eid=uuid4()
    return NormalizedEvidence(
        evidence_id=eid, tenant_id=tenant, channel=channel, source_system=f'test-{channel.value}', source_id=str(eid),
        source_key=f'{channel.value}:{eid}', title=title, content=content, content_hash=('a' if channel is EvidenceChannel.TEXT else 'b' if channel is EvidenceChannel.RUNTIME else 'c')*64,
        relevance_score=relevance, source_confidence=confidence, fusion_score=.9,
        locator=EvidenceLocator(timestamp=datetime(2026,8,17,14,minute,tzinfo=timezone.utc)), estimated_tokens=10,
        provenance={'service':service,'environment':environment},
    )


def request(tenant=None, context=None):
    return AgentRequest(tenant_id=tenant or uuid4(), user_id='sre-1', correlation_id='corr-23', objective='Determine the root cause of checkout latency', context=context or {'service':'checkout','environment':'production'})


def auth(r, allowed=True):
    perms={ToolPermission.RCA_ANALYSIS_READ} if allowed else set()
    return AgentAuthorization(tenant_id=r.tenant_id,user_id=r.user_id,allowed_permissions=frozenset(perms))


def proposal(a,b,c=None, *, disconfirm=None, kind='root_cause', confidence=.9):
    support=[str(a.evidence_id),str(b.evidence_id)]
    hypotheses=[{
        'hypothesis_id':'hyp-01','rank':1,'kind':kind,'statement':'Database connection pool exhaustion caused checkout latency',
        'model_confidence':confidence,'supporting_evidence_ids':support,'disconfirming_evidence_ids':[str(disconfirm.evidence_id)] if disconfirm else [],
        'causal_links':[{'source_evidence_id':support[0],'target_evidence_id':support[1],'relation':'precedes','rationale':'pool saturation preceded request failures'}],
        'temporal_rationale':'runtime saturation and failure evidence align within the incident window',
        'recommended_tests':[{'test_id':'test-01','objective':'Inspect pool utilization and waiting connections','expected_if_true':'saturation remains visible','expected_if_false':'pool remains healthy','risk':'read_only'}],
    }]
    if c is not None:
        hypotheses.append({
            'hypothesis_id':'hyp-02','rank':2,'kind':'trigger','statement':'Traffic spike triggered the latent pool-capacity limit',
            'model_confidence':.7,'supporting_evidence_ids':[str(c.evidence_id)],'disconfirming_evidence_ids':[], 'causal_links':[],
            'temporal_rationale':'traffic event coincides with incident onset','recommended_tests':[]})
    return {'incident_summary':'Checkout latency rose during database saturation','hypotheses':hypotheses,'limitations':[]}


def evidence_set(r):
    a=ev(r.tenant_id,EvidenceChannel.RUNTIME,'DB pool saturation','active connections reached configured maximum',minute=0)
    b=ev(r.tenant_id,EvidenceChannel.TEXT,'Runbook evidence','pool exhaustion produces checkout queueing',minute=3)
    c=ev(r.tenant_id,EvidenceChannel.RUNTIME,'Traffic event','request rate increased sharply',minute=1)
    return a,b,c


def test_rca_schema_requires_contiguous_ranks_and_support_only_causal_links():
    r=request(); a,b,c=evidence_set(r)
    bad=proposal(a,b,c); bad['hypotheses'][1]['rank']=3
    with pytest.raises(ValidationError,match='contiguous'):
        RCAProposal.model_validate(bad)
    bad=proposal(a,b); bad['hypotheses'][0]['causal_links'][0]['target_evidence_id']=str(c.evidence_id)
    with pytest.raises(ValidationError,match='supporting evidence'):
        RCAProposal.model_validate(bad)


@pytest.mark.asyncio
async def test_permission_required_before_model_call():
    r=request(); a,b,c=evidence_set(r); model=FakeModel(proposal(a,b,c))
    agent=RCAAgent(model=model,prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository())
    with pytest.raises(PermissionError): await agent.run(r,authorization=auth(r,False),evidence=[a,b,c])
    assert model.calls==[]


@pytest.mark.asyncio
async def test_unknown_evidence_reference_rejected_and_run_failed():
    r=request(); a,b,c=evidence_set(r); out=proposal(a,b,c); unknown=str(uuid4()); out['hypotheses'][0]['supporting_evidence_ids'][1]=unknown; out['hypotheses'][0]['causal_links'][0]['target_evidence_id']=unknown
    repo=InMemoryAgentRunRepository(); agent=RCAAgent(model=FakeModel(out),prompts=build_prompt_registry(),repository=repo)
    with pytest.raises(ValueError,match='unknown evidence'):
        await agent.run(r,authorization=auth(r),evidence=[a,b,c])
    assert list(repo.records.values())[0].status.value=='FAILED'


@pytest.mark.asyncio
async def test_root_cause_trigger_separation_and_temporal_causal_scoring():
    r=request(); a,b,c=evidence_set(r)
    result=await RCAAgent(model=FakeModel(proposal(a,b,c)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository()).run(r,authorization=auth(r),evidence=[a,b,c])
    assert result.sufficiency.root_cause_determined is True
    assert result.sufficiency.top_hypothesis_id=='hyp-01'
    assert len(result.root_causes)==1 and len(result.triggers)==1
    assert result.root_causes[0].temporal_score==1.0 and result.root_causes[0].causal_score==1.0
    assert result.root_causes[0].adjusted_confidence >= .8


@pytest.mark.asyncio
async def test_disconfirming_evidence_reduces_confidence_and_blocks_determined_cause():
    r=request(); a,b,c=evidence_set(r); d=ev(r.tenant_id,EvidenceChannel.RUNTIME,'Pool health','pool remained below 50 percent',minute=2)
    out=proposal(a,b,c,disconfirm=d,confidence=.75)
    result=await RCAAgent(model=FakeModel(out),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository()).run(r,authorization=auth(r),evidence=[a,b,c,d],min_root_confidence=.7)
    assert result.root_causes[0].contradiction_count==1
    assert result.sufficiency.root_cause_determined is False
    assert 'root_cause_support_or_confidence_insufficient' in result.sufficiency.reason_codes


@pytest.mark.asyncio
async def test_insufficient_support_never_declares_root_cause():
    r=request(); a,b,c=evidence_set(r); out=proposal(a,b,c); out['hypotheses'][0]['supporting_evidence_ids']=[str(a.evidence_id)]; out['hypotheses'][0]['causal_links']=[]
    result=await RCAAgent(model=FakeModel(out),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository()).run(r,authorization=auth(r),evidence=[a,b,c],min_root_support=2)
    assert result.sufficiency.root_cause_determined is False
    assert result.sufficiency.top_hypothesis_id is None


@pytest.mark.asyncio
async def test_required_channel_missing_is_explicit():
    r=request(); a,b,c=evidence_set(r)
    result=await RCAAgent(model=FakeModel(proposal(a,b,c)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository()).run(r,authorization=auth(r),evidence=[a,b,c],required_channels=[EvidenceChannel.VISUAL])
    assert result.sufficiency.root_cause_determined is False
    assert 'required_evidence_channel_missing' in result.sufficiency.reason_codes


@pytest.mark.asyncio
async def test_cross_tenant_and_trusted_scope_evidence_rejected():
    r=request(); a,b,c=evidence_set(r)
    wrong=a.model_copy(update={'tenant_id':uuid4()})
    agent=RCAAgent(model=FakeModel(proposal(a,b,c)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository())
    with pytest.raises(PermissionError,match='tenant'): await agent.run(r,authorization=auth(r),evidence=[wrong,b,c])
    wrong_scope=b.model_copy(update={'provenance':{'service':'payments','environment':'production'}})
    with pytest.raises(PermissionError,match='service'): await agent.run(r,authorization=auth(r),evidence=[a,wrong_scope,c])


@pytest.mark.asyncio
async def test_evidence_maximum_is_enforced_before_model():
    r=request(); a,b,c=evidence_set(r); model=FakeModel(proposal(a,b,c))
    agent=RCAAgent(model=model,prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository())
    with pytest.raises(ValueError,match='maximum'): await agent.run(r,authorization=auth(r),evidence=[a,b,c],max_evidence=2)
    assert not model.calls


def test_supervisor_planner_and_prompt_versions_include_rca():
    SupervisorDecision.model_validate({'route':'rca','rationale':'RCA needed','confidence':.9,'required_permissions':['rca.analysis.read']})
    with pytest.raises(ValidationError,match='rca.analysis.read'):
        SupervisorDecision.model_validate({'route':'rca','rationale':'RCA needed','confidence':.9,'required_permissions':[]})
    AgentPlan.model_validate({'rationale':'collect then analyze','steps':[{'step_id':'step-01','agent':'runtime_evidence','objective':'collect telemetry','required_permissions':['runtime.evidence.read'],'max_tool_calls':2,'depends_on':[]},{'step_id':'step-02','agent':'rca','objective':'rank causes','required_permissions':['rca.analysis.read'],'max_tool_calls':0,'depends_on':['step-01']}]})
    reg=build_prompt_registry()
    assert reg.get('rca','1.0.0').sha256
    assert reg.get('supervisor','1.4.0').sha256 and reg.get('planner','1.4.0').sha256


@pytest.mark.asyncio
async def test_agent_run_persists_prompt_and_input_hash():
    r=request(); a,b,c=evidence_set(r); repo=InMemoryAgentRunRepository()
    result=await RCAAgent(model=FakeModel(proposal(a,b,c)),prompts=build_prompt_registry(),repository=repo).run(r,authorization=auth(r),evidence=[a,b,c])
    record=list(repo.records.values())[0]
    assert record.status.value=='COMPLETED' and record.prompt_name=='rca' and record.prompt_version=='1.0.0'
    assert len(record.prompt_sha256)==64 and len(record.input_sha256)==64 and record.output['sufficiency']['root_cause_determined'] is True


def test_private_rca_endpoint_enforces_service_tenant_and_user_scope():
    r=request(); a,b,c=evidence_set(r)
    class Stub:
        async def run(self,*args,**kwargs):
            return await RCAAgent(model=FakeModel(proposal(a,b,c)),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository()).run(*args,**kwargs)
    app.dependency_overrides[get_rca_agent]=lambda: Stub()
    payload={'request':r.model_dump(mode='json'),'permissions':['rca.analysis.read'],'evidence':[x.model_dump(mode='json') for x in [a,b,c]],'required_channels':['runtime','text']}
    headers={'x-internal-service':'bad','x-tenant-id':str(r.tenant_id),'x-user-id':r.user_id}
    try:
        with TestClient(app) as client:
            assert client.post('/internal/v1/agents/rca',json=payload,headers=headers).status_code==401
            headers['x-internal-service']='verideploy-gateway'; headers['x-tenant-id']=str(uuid4())
            assert client.post('/internal/v1/agents/rca',json=payload,headers=headers).status_code==403
            headers['x-tenant-id']=str(r.tenant_id); headers['x-user-id']='other'
            assert client.post('/internal/v1/agents/rca',json=payload,headers=headers).status_code==403
            headers['x-user-id']=r.user_id
            response=client.post('/internal/v1/agents/rca',json=payload,headers=headers)
            assert response.status_code==200 and response.json()['sufficiency']['root_cause_determined'] is True
    finally:
        app.dependency_overrides.pop(get_rca_agent,None)


def test_recommended_tests_are_bounded_and_risk_qualified():
    r=request(); a,b,c=evidence_set(r); out=proposal(a,b,c)
    tests=out['hypotheses'][0]['recommended_tests']
    tests[0]['risk']='requires_approval'
    parsed=RCAProposal.model_validate(out)
    assert parsed.hypotheses[0].recommended_tests[0].risk=='requires_approval'
    out=proposal(a,b,c); out['hypotheses'][0]['recommended_tests']=[dict(out['hypotheses'][0]['recommended_tests'][0],test_id=f'test-{i:02d}') for i in range(1,7)]
    with pytest.raises(ValidationError): RCAProposal.model_validate(out)
