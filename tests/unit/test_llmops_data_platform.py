from pathlib import Path
from uuid import uuid4
from verideploy.llmops.repository import InMemoryLLMOpsRepository
from verideploy.llmops.service import LLMOpsService,redact_payload
from verideploy.llmops.schemas import LLMOpsEvent,LLMOpsKind
ROOT=Path(__file__).resolve().parents[2]
def test_trace_end_to_end_by_correlation():
 t=uuid4(); c='corr-1'; s=LLMOpsService(InMemoryLLMOpsRepository())
 for e in [LLMOpsEvent(tenant_id=t,correlation_id=c,kind=LLMOpsKind.MODEL_CALL,operation='model',prompt_version='v1',input_tokens=10,output_tokens=5,total_tokens=15,cost_usd=.02,latency_ms=8,retry_count=1),LLMOpsEvent(tenant_id=t,correlation_id=c,kind=LLMOpsKind.RETRIEVAL,operation='retrieve',retrieval_count=4,confidence=.7),LLMOpsEvent(tenant_id=t,correlation_id=c,kind=LLMOpsKind.TOOL_CALL,operation='tool',tool_name='x')]: s.record(e)
 tr=s.trace(tenant_id=t,correlation_id=c); assert (tr.model_calls,tr.tool_calls,tr.retrieval_calls,tr.total_tokens,tr.retries)==(1,1,1,15,1); assert tr.latest_confidence==.7
def test_redaction_before_persistence():
 assert redact_payload({'password':'x','nested':{'access_token':'y'},'safe':'z'})=={'password':'[REDACTED]','nested':{'access_token':'[REDACTED]'},'safe':'z'}
def test_tenant_isolation_memory():
 r=InMemoryLLMOpsRepository(); a,b=uuid4(),uuid4(); r.append(LLMOpsEvent(tenant_id=a,correlation_id='c',kind=LLMOpsKind.AGENT,operation='a')); assert r.list_by_correlation(tenant_id=b,correlation_id='c')==[]
def test_migration_contract():
 s=(ROOT/'src/verideploy/database/migrations/versions/0025_llmops_data_platform.py').read_text();
 for token in ['llmops_events','ix_correlation_trace','ENABLE ROW LEVEL SECURITY','FORCE ROW LEVEL SECURITY','append-only','retention_class']: assert token in s
def test_api_contract():
 s=(ROOT/'services/ai/routes/llmops.py').read_text(); m=(ROOT/'services/ai/main.py').read_text(); assert '/correlations/{correlation_id}' in s and 'llmops_router' in m
def test_version_bumped():
 import verideploy; assert tuple(map(int,verideploy.__version__.split('.'))) >= (0,48,0)


import asyncio
from verideploy.llmops.sinks import LLMOpsModelCallSink
from verideploy.llm.contracts import AIRequest,AIResult,AIUsage,AIProviderName
from verideploy.llm.routing import ModelRole
def test_model_sink_persists_usage_prompt_cost():
 t=uuid4(); repo=InMemoryLLMOpsRepository(); service=LLMOpsService(repo); sink=LLMOpsModelCallSink(service)
 req=AIRequest(tenant_id=t,correlation_id='corr-model',operation='agent.rca',model_role=ModelRole.STANDARD,input='x',metadata={'prompt_name':'rca','prompt_version':'1.2','prompt_sha256':'a'*64})
 res=AIResult(request_id=req.request_id,provider=AIProviderName.TEST,model_role=ModelRole.STANDARD,model='test-model',output_text='ok',usage=AIUsage(input_tokens=7,output_tokens=3,total_tokens=10),latency_ms=1,attempts=2,actual_cost_usd='0.012')
 asyncio.run(sink.success(request=req,result=res,latency_ms=9.5)); e=repo.list_by_correlation(tenant_id=t,correlation_id='corr-model')[0]; assert (e.total_tokens,e.retry_count,e.prompt_version,e.cost_usd)==(10,1,'1.2',.012)

from datetime import datetime,timezone,timedelta
def test_retention_purge_is_explicit_and_tenant_scoped():
 r=InMemoryLLMOpsRepository(); a,b=uuid4(),uuid4(); old=datetime.now(timezone.utc)-timedelta(days=100)
 r.append(LLMOpsEvent(tenant_id=a,correlation_id='x',kind=LLMOpsKind.AGENT,operation='a',occurred_at=old)); r.append(LLMOpsEvent(tenant_id=b,correlation_id='x',kind=LLMOpsKind.AGENT,operation='b',occurred_at=old)); assert r.purge_before(tenant_id=a,before=datetime.now(timezone.utc)-timedelta(days=90))==1; assert len(r.items)==1 and r.items[0].tenant_id==b

def test_retrieval_route_emits_correlation_llmops_fact():
 text=(ROOT/'services/ai/routes/retrieval.py').read_text(); assert 'x_correlation_id' in text and 'LLMOpsKind.RETRIEVAL' in text and 'retrieval_count=len(result.candidates)' in text

def test_public_gateway_trace_boundary():
 app=(ROOT/'apps/gateway/src/app.module.ts').read_text(); svc=(ROOT/'apps/gateway/src/llmops/llmops.service.ts').read_text(); contract=(ROOT/'contracts/openapi/gateway.yaml').read_text(); import re; m=re.search(r'version: (\d+)\.(\d+)\.(\d+)', contract); assert 'LLMOpsModule' in app and '/internal/v1/llmops/correlations/' in svc and '/llmops/correlations/{correlationId}' in contract and m and tuple(map(int,m.groups())) >= (0,48,0)
