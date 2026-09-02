from uuid import uuid4
from verideploy.llmops.repository import InMemoryLLMOpsRepository
from verideploy.llmops.service import LLMOpsService
from verideploy.llmops.schemas import LLMOpsEvent,LLMOpsKind
t=uuid4(); c='corr'; r=InMemoryLLMOpsRepository(); s=LLMOpsService(r)
s.record(LLMOpsEvent(tenant_id=t,correlation_id=c,kind=LLMOpsKind.MODEL_CALL,operation='agent.rca',prompt_name='rca',prompt_version='1.0.0',model_role='reasoning',model_name='gpt-test',input_tokens=100,output_tokens=20,total_tokens=120,latency_ms=50,cost_usd=.01,retry_count=1,payload={'api_key':'x'}))
s.record(LLMOpsEvent(tenant_id=t,correlation_id=c,kind=LLMOpsKind.RETRIEVAL,operation='rag.retrieve',retrieval_count=8,latency_ms=12,confidence=.82))
s.record(LLMOpsEvent(tenant_id=t,correlation_id=c,kind=LLMOpsKind.TOOL_CALL,operation='mcp.github',tool_name='github.pull_request.get',latency_ms=5))
tr=s.trace(tenant_id=t,correlation_id=c)
assert tr.model_calls==1 and tr.tool_calls==1 and tr.retrieval_calls==1 and tr.total_tokens==120 and tr.retries==1 and tr.latest_confidence==.82
assert tr.events[0].payload.get('api_key')=='[REDACTED]'
print({'valid':True,'correlation_id':c,'events':len(tr.events),'tokens':tr.total_tokens,'cost_usd':tr.total_cost_usd,'latest_confidence':tr.latest_confidence})
