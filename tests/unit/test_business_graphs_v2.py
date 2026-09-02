from __future__ import annotations

from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver

from types import SimpleNamespace
from verideploy.graphs.incident_rca_v2 import AGENT_SEQUENCE, incident_rca_definition
from verideploy.graphs.release_risk_v2 import build_release_risk_graph
from verideploy.graphs.memory_repository import InMemoryGraphRuntimeRepository
from verideploy.graphs.runtime import GraphDefinition, GraphRegistry, GraphRunStatus, LangGraphRuntime
from verideploy.agents.rag_tools import ProductionRAGTool
from verideploy.rag.retrieval.schemas import RetrievalChannel, RetrievalDocumentKind, RetrievalQuery
from verideploy.graphs.retry import FailureClass, classify_failure, retry_transient
from pydantic import BaseModel, ValidationError


def test_incident_graph_contains_in_process_agent_and_business_nodes():
    agents = SimpleNamespace(supervisor=None, planning=None, github=None, rag=None, visual_evidence=None,
                             runtime_evidence=None, rca=None, critic=None, claim_verifier=None, citation_service=None, approval_service=None, settings=None)
    graph = incident_rca_definition(agents).factory(MemorySaver())
    assert set(AGENT_SEQUENCE).issubset(graph.get_graph().nodes)
    assert AGENT_SEQUENCE[AGENT_SEQUENCE.index("critic"):AGENT_SEQUENCE.index("approval")+1] == ("critic","verify_claims","validate_citations","approval")
    assert {"planner_repair","rag_rewrite","human_review_error","safe_terminate","degraded_finalize"}.issubset(graph.get_graph().nodes)
    assert graph.nodes["github"].bound.nodes["execute"].retry_policy[0].max_attempts == 3
    assert graph.nodes["supervisor"].retry_policy[0].max_attempts == 4
    assert graph.nodes["github"].bound.checkpointer is None


def test_failure_classifier_never_retries_policy_or_bad_input_failures():
    class Input(BaseModel): value: int
    validation=None
    try: Input.model_validate({"value":"bad"})
    except ValidationError as exc: validation=exc
    assert validation is not None
    assert classify_failure(validation) is FailureClass.USER_FIXABLE
    assert classify_failure(PermissionError("denied")) is FailureClass.AUTHORIZATION
    assert classify_failure(RuntimeError("prompt injection pattern detected")) is FailureClass.PROMPT_INJECTION
    assert not retry_transient(validation)
    assert not retry_transient(PermissionError("denied"))
    assert classify_failure(TimeoutError("prometheus timed out"),node_name="runtime_evidence") is FailureClass.TRANSIENT
    assert classify_failure(TimeoutError("openai timed out"),node_name="critic") is FailureClass.TRANSIENT


@pytest.mark.asyncio
async def test_release_graph_runs_real_risk_engine():
    assessment_id = uuid4()
    graph = build_release_risk_graph(MemorySaver())
    result = await graph.ainvoke(
        {"input": {"assessment_id": str(assessment_id), "release_id": "v2",
                   "policy": {"changed_files": 2, "changed_services": 1,
                              "security_scan_critical_findings": 1},
                   "human_review_threshold": 80},
         "completed_nodes": [], "node_outputs": {}, "evidence_ids": []},
        config={"configurable": {"thread_id": "release-test"}},
    )
    assert result["final_output"]["assessment_id"] == str(assessment_id)
    assert result["final_output"]["decision"] == "BLOCK"


@pytest.mark.asyncio
async def test_runtime_interrupts_and_resumes_same_thread_with_command():
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt
    from verideploy.graphs.state import GraphExecutionState

    def build(checkpointer):
        def approval(state):
            decision=interrupt({"action":"rollback","risk":"high","dry_run":{"ok":True}})
            return {"approval_state":{"status":decision["decision"]},"final_output":{"decision":decision["decision"]}}
        graph=StateGraph(GraphExecutionState); graph.add_node("approval",approval); graph.add_edge(START,"approval"); graph.add_edge("approval",END)
        return graph.compile(checkpointer=checkpointer)

    registry=GraphRegistry(); registry.register(GraphDefinition(name="approval-test",version="1",factory=build))
    runtime=LangGraphRuntime(registry=registry,repository=InMemoryGraphRuntimeRepository(),checkpointer=MemorySaver())
    tenant,run_id=uuid4(),uuid4(); thread_id="stable-approval-thread"
    waiting,paused=await runtime.execute(tenant_id=tenant,correlation_id="corr",graph_name="approval-test",graph_version="1",input_state={},run_id=run_id,thread_id=thread_id)
    assert waiting.status == GraphRunStatus.WAITING_FOR_APPROVAL
    assert paused["__interrupt__"][0].value["action"] == "rollback"
    completed,result=await runtime.execute(tenant_id=tenant,correlation_id="corr",graph_name="approval-test",graph_version="1",input_state={},run_id=run_id,thread_id=thread_id,resume_value={"decision":"approve"})
    assert completed.status == GraphRunStatus.COMPLETED
    assert result["final_output"]["decision"] == "approve"


@pytest.mark.asyncio
async def test_production_rag_tool_uses_self_corrective_parent_context():
    tenant,chunk,document,run_id=uuid4(),uuid4(),uuid4(),uuid4()
    candidate=SimpleNamespace(chunk_id=chunk,document_id=document,source_key="runbook",title="Rollback",content="child",document_kind=RetrievalDocumentKind.RUNBOOK,retrieval_score=.4,rerank_score=.8,final_rank=1,channels=[RetrievalChannel.HYBRID])
    context=SimpleNamespace(chunk_id=chunk,content="expanded parent operational context")
    result=SimpleNamespace(run_id=run_id,answerable=True,stop_reason=SimpleNamespace(value="sufficient_evidence"),final_retrieval=SimpleNamespace(candidates=[candidate],context=[context]))
    class Controller:
        async def run(self, request, *, authorization):
            self.request=request; self.authorization=authorization; return result
    controller=Controller(); tool=ProductionRAGTool(controller)
    output=await tool.retrieve(RetrievalQuery(tenant_id=tenant,text="rollback evidence",top_k=1,candidate_k=2,model_name="embed",dimensions=8),mode=RetrievalChannel.HYBRID)
    assert controller.request.max_attempts == 3
    assert output.hits[0].content == "expanded parent operational context"
    assert output.trace.trace_id == run_id
