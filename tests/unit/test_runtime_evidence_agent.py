from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from verideploy.agents.contracts import AgentAuthorization, AgentRequest, ToolBudget, ToolPermission, SupervisorDecision, AgentPlan, PlanStep
from verideploy.agents.prompts import build_prompt_registry
from verideploy.agents.repository import InMemoryAgentRunRepository
from verideploy.agents.runtime import RuntimeEvidenceAgent, RuntimeQueryAnalysis
from verideploy.agents.runtime_tools import RuntimeSource, RuntimeToolResult, RuntimePoint, SyntheticRuntimeTool


class FakeModel:
    def __init__(self, output): self.output=output; self.calls=[]
    async def generate(self, **kwargs): self.calls.append(kwargs); return kwargs['output_model'].model_validate(self.output)


class RecordingTool:
    def __init__(self, source, *, fail=False, current=30.0, baseline=10.0): self.source=source; self.fail=fail; self.current=current; self.baseline=baseline; self.calls=[]
    async def query(self, request):
        self.calls.append(request)
        if self.fail: raise ConnectionError('source unavailable')
        return RuntimeToolResult(source=self.source, source_system=f'test-{self.source.value}', query=request.query,
            points=[RuntimePoint(observed_at=request.end,value=self.current,text=f'{self.source.value} evidence',source_id=f'{self.source.value}-1')],
            baseline_points=[RuntimePoint(observed_at=request.baseline_end,value=self.baseline,source_id=f'{self.source.value}-base')])


def req(context=None):
    tenant=uuid4(); base={'service':'checkout','environment':'production','window_start':'2026-08-17T14:00:00Z','window_end':'2026-08-17T15:00:00Z'}
    base.update(context or {})
    return AgentRequest(tenant_id=tenant,user_id='sre-1',correlation_id='corr-22',objective='Investigate checkout runtime degradation',context=base)

def auth(r, allowed=True):
    perms={ToolPermission.RUNTIME_EVIDENCE_READ} if allowed else set()
    return AgentAuthorization(tenant_id=r.tenant_id,user_id=r.user_id,allowed_permissions=frozenset(perms))

def analysis(**overrides):
    x={'service':'checkout','environment':'production','window_start':'2026-08-17T17:00:00+03:00','window_end':'2026-08-17T18:00:00+03:00','baseline_minutes':60,
       'sources':[{'source':'prometheus','query':'rate(http_requests_total{service="checkout"}[5m])'},{'source':'log','query':'{service="checkout"} |= "error"'}],
       'rationale':'metrics and logs directly cover the degradation window'}
    x.update(overrides); return x


def test_time_window_normalizes_to_utc_and_rejects_naive_or_oversized():
    item=RuntimeQueryAnalysis.model_validate(analysis())
    assert item.window_start == datetime(2026,8,17,14,tzinfo=timezone.utc)
    assert item.window_end == datetime(2026,8,17,15,tzinfo=timezone.utc)
    with pytest.raises(ValidationError, match='timezone-aware'):
        RuntimeQueryAnalysis.model_validate(analysis(window_start='2026-08-17T14:00:00'))
    with pytest.raises(ValidationError, match='24 hours'):
        RuntimeQueryAnalysis.model_validate(analysis(window_start='2026-08-15T14:00:00Z'))


def test_duplicate_sources_rejected():
    with pytest.raises(ValidationError, match='duplicate runtime source'):
        RuntimeQueryAnalysis.model_validate(analysis(sources=[{'source':'log','query':'a'},{'source':'log','query':'b'}]))


@pytest.mark.asyncio
async def test_permission_required_before_model_or_tools():
    r=req(); model=FakeModel(analysis()); tool=RecordingTool(RuntimeSource.PROMETHEUS)
    agent=RuntimeEvidenceAgent(model=model,prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),tools={RuntimeSource.PROMETHEUS:tool})
    with pytest.raises(PermissionError): await agent.run(r,authorization=auth(r,False),budget=ToolBudget(max_calls=2))
    assert not model.calls and not tool.calls


@pytest.mark.asyncio
async def test_trusted_scope_and_baseline_are_authoritative_and_reproducible():
    r=req(); p=RecordingTool(RuntimeSource.PROMETHEUS); l=RecordingTool(RuntimeSource.LOG)
    agent=RuntimeEvidenceAgent(model=FakeModel(analysis()),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),tools={RuntimeSource.PROMETHEUS:p,RuntimeSource.LOG:l})
    result=await agent.run(r,authorization=auth(r),budget=ToolBudget(max_calls=2))
    q=p.calls[0]
    assert q.start==datetime(2026,8,17,14,tzinfo=timezone.utc) and q.end==datetime(2026,8,17,15,tzinfo=timezone.utc)
    assert q.baseline_start==datetime(2026,8,17,13,tzinfo=timezone.utc) and q.baseline_end==q.start
    assert result.tool_calls_used==2 and result.sufficiency.sufficient is True


@pytest.mark.asyncio
async def test_model_cannot_broaden_service_environment_or_time_scope():
    for changed in [analysis(service='payments'), analysis(environment='staging'), analysis(window_end='2026-08-17T18:05:00+03:00')]:
        r=req(); agent=RuntimeEvidenceAgent(model=FakeModel(changed),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),tools={s:SyntheticRuntimeTool(s) for s in RuntimeSource})
        with pytest.raises(PermissionError, match='cannot'):
            await agent.run(r,authorization=auth(r),budget=ToolBudget(max_calls=4))


@pytest.mark.asyncio
async def test_budget_rejects_plan_before_runtime_tools_execute():
    r=req(); p=RecordingTool(RuntimeSource.PROMETHEUS); l=RecordingTool(RuntimeSource.LOG)
    agent=RuntimeEvidenceAgent(model=FakeModel(analysis()),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),tools={RuntimeSource.PROMETHEUS:p,RuntimeSource.LOG:l})
    with pytest.raises(RuntimeError, match='exceeds tool-call budget'): await agent.run(r,authorization=auth(r),budget=ToolBudget(max_calls=1))
    assert not p.calls and not l.calls


@pytest.mark.asyncio
async def test_source_failure_degrades_without_shifting_other_source_windows():
    r=req(); p=RecordingTool(RuntimeSource.PROMETHEUS, fail=True); l=RecordingTool(RuntimeSource.LOG)
    agent=RuntimeEvidenceAgent(model=FakeModel(analysis()),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),tools={RuntimeSource.PROMETHEUS:p,RuntimeSource.LOG:l})
    result=await agent.run(r,authorization=auth(r),budget=ToolBudget(max_calls=2))
    assert result.sufficiency.sufficient is True and 'runtime_source_failure' in result.sufficiency.reason_codes
    assert result.sufficiency.failed_sources==1 and result.sufficiency.successful_sources==1
    assert p.calls[0].start==l.calls[0].start and p.calls[0].end==l.calls[0].end
    assert p.calls[0].baseline_start==l.calls[0].baseline_start


@pytest.mark.asyncio
async def test_all_source_failures_are_explicitly_insufficient():
    r=req(); p=RecordingTool(RuntimeSource.PROMETHEUS,fail=True); l=RecordingTool(RuntimeSource.LOG,fail=True)
    result=await RuntimeEvidenceAgent(model=FakeModel(analysis()),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),tools={RuntimeSource.PROMETHEUS:p,RuntimeSource.LOG:l}).run(r,authorization=auth(r),budget=ToolBudget(max_calls=2))
    assert result.evidence==[] and result.sufficiency.sufficient is False
    assert {'insufficient_runtime_evidence','insufficient_runtime_sources','runtime_source_failure'} <= set(result.sufficiency.reason_codes)


@pytest.mark.asyncio
async def test_anomaly_and_runtime_evidence_are_deterministic():
    r=req(); p=RecordingTool(RuntimeSource.PROMETHEUS,current=30,baseline=10)
    one=analysis(sources=[{'source':'prometheus','query':'up'}])
    agent=RuntimeEvidenceAgent(model=FakeModel(one),prompts=build_prompt_registry(),repository=InMemoryAgentRunRepository(),tools={RuntimeSource.PROMETHEUS:p})
    result=await agent.run(r,authorization=auth(r),budget=ToolBudget(max_calls=1),anomaly_percent_threshold=50)
    assert result.anomalies[0].anomalous is True and result.anomalies[0].percent_change==pytest.approx(200)
    ev=result.evidence[0]
    assert ev.kind.value=='metric' and ev.service=='checkout' and ev.environment=='production'
    assert ev.observed_at==datetime(2026,8,17,15,tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_synthetic_adapter_is_reproducible_for_same_scope():
    r=req(); q=RuntimeQueryAnalysis.model_validate(analysis(sources=[{'source':'trace','query':'{ resource.service.name = "checkout" }'}]))
    tool=SyntheticRuntimeTool(RuntimeSource.TRACE)
    from verideploy.agents.runtime_tools import RuntimeToolQuery
    query=RuntimeToolQuery(tenant_id=r.tenant_id,source=RuntimeSource.TRACE,query=q.sources[0].query,service=q.service,environment=q.environment,start=q.window_start,end=q.window_end,baseline_start=q.window_start-timedelta(hours=1),baseline_end=q.window_start)
    a=await tool.query(query); b=await tool.query(query)
    assert a.model_dump()==b.model_dump()


def test_prompt_and_supervisor_planner_contracts():
    registry=build_prompt_registry()
    assert len(registry.get('runtime_evidence','1.0.0').sha256)==64
    assert len(registry.get('supervisor','1.3.0').sha256)==64
    d=SupervisorDecision(route='runtime_evidence',rationale='runtime signals needed',confidence=.9,required_permissions=['runtime.evidence.read'])
    p=AgentPlan(rationale='inspect runtime',steps=[PlanStep(step_id='step-01',agent='runtime_evidence',objective='inspect metrics/logs',required_permissions=['runtime.evidence.read'],max_tool_calls=4)])
    assert d.required_permissions==[ToolPermission.RUNTIME_EVIDENCE_READ] and p.steps[0].agent=='runtime_evidence'


def test_runtime_agent_private_route_enforces_service_and_tenant():
    from fastapi.testclient import TestClient
    from services.ai.main import app
    from services.ai.agents import get_runtime_evidence_agent
    from verideploy.agents.runtime import RuntimeEvidenceAgentResult, RuntimeEvidenceSufficiency
    r=req(); an=RuntimeQueryAnalysis.model_validate(analysis())
    expected=RuntimeEvidenceAgentResult(analysis=an,evidence=[],anomalies=[],source_executions=[],sufficiency=RuntimeEvidenceSufficiency(sufficient=False,evidence_count=0,successful_sources=0,failed_sources=0,anomalous_sources=0,reason_codes=['insufficient_runtime_evidence']),tool_calls_used=0)
    class Fake:
        async def run(self, *a, **k):
            return expected
    app.dependency_overrides[get_runtime_evidence_agent]=lambda:Fake()
    try:
        client=TestClient(app); payload={'request':r.model_dump(mode='json'),'permissions':['runtime.evidence.read']}
        headers={'x-internal-service':'unknown','x-tenant-id':str(r.tenant_id),'x-user-id':r.user_id}
        assert client.post('/internal/v1/agents/runtime-evidence',json=payload,headers=headers).status_code==401
        headers['x-internal-service']='verideploy-gateway'; headers['x-tenant-id']=str(uuid4())
        assert client.post('/internal/v1/agents/runtime-evidence',json=payload,headers=headers).status_code==403
        headers['x-tenant-id']=str(r.tenant_id)
        assert client.post('/internal/v1/agents/runtime-evidence',json=payload,headers=headers).status_code==200
    finally: app.dependency_overrides.pop(get_runtime_evidence_agent,None)

@pytest.mark.asyncio
@pytest.mark.parametrize('source', [RuntimeSource.PROMETHEUS, RuntimeSource.LOG, RuntimeSource.GRAFANA, RuntimeSource.TRACE])
async def test_live_runtime_http_contracts_are_read_only_and_time_bounded(source):
    import json
    import httpx
    from urllib.parse import parse_qs
    from verideploy.agents.runtime_tools import LiveRuntimeEndpoints, LiveRuntimeTool, RuntimeToolQuery
    seen=[]
    def handler(request: httpx.Request):
        seen.append(request)
        path=request.url.path
        if source is RuntimeSource.PROMETHEUS:
            payload={'status':'success','data':{'resultType':'matrix','result':[{'metric':{'service':'checkout'},'values':[[1786971600,'2.0']]}]}}
        elif source is RuntimeSource.LOG:
            payload={'status':'success','data':{'resultType':'streams','result':[{'stream':{'service':'checkout'},'values':[['1786971600000000000','error line']]}]}}
        elif source is RuntimeSource.GRAFANA:
            payload=[{'id':7,'time':1786971600000,'text':'deploy annotation','dashboardUID':'ops','panelId':2}]
        else:
            payload={'traces':[{'traceID':'abc','startTimeUnixNano':'1786971600000000000','durationMs':150.0,'rootServiceName':'checkout','rootTraceName':'GET /pay'}]}
        return httpx.Response(200,json=payload)
    transport=httpx.MockTransport(handler)
    endpoints=LiveRuntimeEndpoints(prometheus_url='https://obs.local/prom',loki_url='https://obs.local/loki',grafana_url='https://obs.local/grafana',tempo_url='https://obs.local/tempo')
    tool=LiveRuntimeTool(source,endpoints,transport=transport)
    scoped_query={RuntimeSource.PROMETHEUS:'up{service=\"checkout\",environment=\"production\"}',RuntimeSource.LOG:'{service=\"checkout\",environment=\"production\"}',RuntimeSource.GRAFANA:'deploy,incident',RuntimeSource.TRACE:'{ resource.service.name = \"checkout\" && deployment.environment.name = \"production\" }'}[source]
    q=RuntimeToolQuery(tenant_id=uuid4(),source=source,query=scoped_query,service='checkout',environment='production',start=datetime(2026,8,17,14,tzinfo=timezone.utc),end=datetime(2026,8,17,15,tzinfo=timezone.utc),baseline_start=datetime(2026,8,17,13,tzinfo=timezone.utc),baseline_end=datetime(2026,8,17,14,tzinfo=timezone.utc))
    result=await tool.query(q)
    assert len(seen)==2 and all(r.method=='GET' for r in seen)
    assert result.points and result.baseline_points
    if source is RuntimeSource.PROMETHEUS:
        assert all(r.url.path.endswith('/api/v1/query_range') for r in seen)
        assert 'start' in dict(seen[0].url.params) and 'end' in dict(seen[0].url.params)
    elif source is RuntimeSource.LOG:
        assert all(r.url.path.endswith('/loki/api/v1/query_range') for r in seen)
    elif source is RuntimeSource.GRAFANA:
        assert all(r.url.path.endswith('/api/annotations') for r in seen)
    else:
        assert all(r.url.path.endswith('/api/search') for r in seen)


@pytest.mark.asyncio
async def test_live_adapter_rejects_unscoped_model_query_before_http():
    import httpx
    from verideploy.agents.runtime_tools import LiveRuntimeEndpoints, LiveRuntimeTool, RuntimeToolQuery
    called=False
    def handler(request):
        nonlocal called; called=True; return httpx.Response(200,json={})
    tool=LiveRuntimeTool(RuntimeSource.PROMETHEUS,LiveRuntimeEndpoints(prometheus_url='https://obs.local'),transport=httpx.MockTransport(handler))
    q=RuntimeToolQuery(tenant_id=uuid4(),source=RuntimeSource.PROMETHEUS,query='up',service='checkout',environment='production',start=datetime(2026,8,17,14,tzinfo=timezone.utc),end=datetime(2026,8,17,15,tzinfo=timezone.utc),baseline_start=datetime(2026,8,17,13,tzinfo=timezone.utc),baseline_end=datetime(2026,8,17,14,tzinfo=timezone.utc))
    with pytest.raises(PermissionError,match='trusted service and environment'):
        await tool.query(q)
    assert called is False
