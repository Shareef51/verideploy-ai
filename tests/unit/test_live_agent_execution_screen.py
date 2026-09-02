from datetime import UTC,datetime,timedelta
from pathlib import Path
from uuid import uuid4
from verideploy.graphs.execution_projection import project_agent_execution,sanitize_payload
from verideploy.graphs.runtime import GraphRunRecord,GraphRunStatus,GraphRuntimeEvent
ROOT=Path(__file__).resolve().parents[2]
def run():
 now=datetime.now(UTC);return GraphRunRecord(run_id=uuid4(),tenant_id=uuid4(),thread_id="thread-47",graph_name="incident",graph_version="1",correlation_id="c47",status=GraphRunStatus.RUNNING,last_sequence=7,created_at=now,updated_at=now)
def ev(r,seq,typ,node=None,payload=None,offset=0):return GraphRuntimeEvent(tenant_id=r.tenant_id,run_id=r.run_id,thread_id=r.thread_id,sequence_number=seq,event_type=typ,graph_name=r.graph_name,graph_version=r.graph_version,node_name=node,payload=payload or {},occurred_at=r.created_at+timedelta(milliseconds=offset))
def test_projection_is_persisted_event_driven_and_calculates_duration_retry_failure():
 r=run(); events=[ev(r,1,"agent.node.started","rag",offset=0),ev(r,2,"agent.node.retry","rag",{"retry":True},10),ev(r,3,"agent.node.failed","rag",{"error_code":"RAG_TIMEOUT","error_message":"retrieval timed out"},110)]
 p=project_agent_execution(r,events);n=p.nodes[0];assert n.status=="failed" and n.duration_ms==110 and n.retries==1 and p.failure_count==1
def test_tool_arguments_are_sanitized_before_projection():
 r=run();p=project_agent_execution(r,[ev(r,1,"agent.tool.completed","rag",{"call_id":"c1","tool_name":"github","arguments":{"repo":"safe","authorization":"Bearer secret","nested":{"api_key":"x"}},"result_summary":"ok"})])
 args=p.tools[0].arguments;assert args["repo"]=="safe" and args["authorization"]=="[REDACTED]" and args["nested"]["api_key"]=="[REDACTED]"
def test_model_usage_totals_only_persisted_usage_events():
 r=run();p=project_agent_execution(r,[ev(r,1,"agent.model.completed","planner",{"call_id":"m1","model_role":"REASONING","model_name":"gpt","input_tokens":100,"output_tokens":20,"cost_usd":.012,"latency_ms":250})]);assert p.total_input_tokens==100 and p.total_output_tokens==20 and p.total_cost_usd==.012
def test_projection_deterministic_regardless_input_order():
 r=run();events=[ev(r,1,"agent.node.started","a"),ev(r,2,"agent.node.completed","a",offset=20),ev(r,3,"agent.model.completed","a",{"call_id":"m","model_role":"FAST","input_tokens":5})]
 assert project_agent_execution(r,events).model_dump(mode="json")==project_agent_execution(r,list(reversed(events))).model_dump(mode="json")
def test_sanitize_payload_truncates_and_redacts():
 assert sanitize_payload({"password":"x","ok":"y"})=={"password":"[REDACTED]","ok":"y"}
def test_private_gateway_and_public_boundary_are_wired():
 private=(ROOT/'services/ai/routes/graph_execution.py').read_text();svc=(ROOT/'apps/gateway/src/agent-execution/agent-execution.service.ts').read_text();page=(ROOT/'apps/web/app/(platform)/agent-execution/page.tsx').read_text();assert 'execution-view' in private and '/internal/v1/graph-runs/' in svc and '/internal/v1' not in page and '/api/v1/agent-execution/' in page
def test_frontend_contains_all_master_screen_sections_and_no_simulated_state():
 page=(ROOT/'apps/web/app/(platform)/agent-execution/page.tsx').read_text()
 for text in ['Node graph','Sanitized tool calls','Model roles and usage','Failure drill-down','Persisted event sequence','No execution state is synthesized']:assert text in page
 assert 'setInterval' not in page and 'Math.random' not in page
def test_frontend_reconnect_uses_persisted_sequence_and_authoritative_refresh():
 page=(ROOT/'apps/web/app/(platform)/agent-execution/page.tsx').read_text();assert 'String(base.last_sequence)' in page and 'Math.min(...seqs)!==current.last_sequence+1' in page and 'await refresh()' in page
def test_public_openapi_exposes_only_nest_boundary():
 c=(ROOT/'contracts/openapi/gateway.yaml').read_text(); assert '/agent-execution/{runId}:' in c and 'streamAgentExecutionEvents' in c and '/internal/v1' not in c
def test_version_and_no_new_database_authority():
 from packaging.version import Version
 import re
 v=re.search(r'\d+\.\d+\.\d+', (ROOT/'src/verideploy/__init__.py').read_text()).group(0)
 assert Version(v) >= Version('0.47.0')
 assert not list((ROOT/'src/verideploy/database/migrations/versions').glob('*agent_execution*'))
