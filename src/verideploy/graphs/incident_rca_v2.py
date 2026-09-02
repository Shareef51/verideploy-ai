from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any, TypedDict
from datetime import datetime, timezone
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from verideploy.agents.contracts import AgentAuthorization, AgentRequest, ToolBudget, ToolPermission
from verideploy.config import Settings
from verideploy.graphs.runtime import DeterministicNodeWrapper, GraphDefinition
from verideploy.graphs.state import GraphExecutionState
from verideploy.graphs.retry import FailureClass, GraphBudgetExceeded, error_state, retry_transient
from verideploy.rag.fusion.schemas import EvidenceChannel, EvidenceLocator, NormalizedEvidence

if TYPE_CHECKING:
    from verideploy.agents.critic import CriticAgent
    from verideploy.agents.github import GitHubAgent
    from verideploy.agents.planner import PlanningAgent
    from verideploy.agents.rag import RAGAgent
    from verideploy.agents.rca import RCAAgent
    from verideploy.agents.runtime import RuntimeEvidenceAgent
    from verideploy.agents.supervisor import SupervisorAgent
    from verideploy.agents.visual import VisualEvidenceAgent


@dataclass(frozen=True)
class IncidentAgentBundle:
    supervisor: SupervisorAgent
    planning: PlanningAgent
    github: GitHubAgent
    rag: RAGAgent
    visual_evidence: VisualEvidenceAgent
    runtime_evidence: RuntimeEvidenceAgent
    rca: RCAAgent
    critic: CriticAgent
    claim_verifier: Any
    citation_service: Any
    approval_service: Any
    settings: Settings


AGENT_SEQUENCE = ("supervisor", "planning", "github", "rag", "visual_evidence", "runtime_evidence", "fuse_evidence", "rca", "critic", "verify_claims", "validate_citations", "approval", "finalize")


class GitHubSubgraphState(TypedDict, total=False):
    tenant_id:str; user_id:str; correlation_id:str; input:dict[str,Any]; completed_nodes:list[str]; github_evidence:dict[str,Any]; agent_outputs:dict[str,Any]; last_error:dict[str,Any]; errors:list[dict[str,Any]]; graph_budget:dict[str,Any]
class RAGSubgraphState(TypedDict, total=False):
    tenant_id:str; user_id:str; correlation_id:str; input:dict[str,Any]; completed_nodes:list[str]; rag_evidence:dict[str,Any]; agent_outputs:dict[str,Any]; evidence_ids:list[str]; last_error:dict[str,Any]; errors:list[dict[str,Any]]; graph_budget:dict[str,Any]
class VisualSubgraphState(TypedDict, total=False):
    tenant_id:str; user_id:str; correlation_id:str; input:dict[str,Any]; completed_nodes:list[str]; visual_evidence:dict[str,Any]; agent_outputs:dict[str,Any]; evidence_ids:list[str]; last_error:dict[str,Any]; errors:list[dict[str,Any]]; graph_budget:dict[str,Any]
class RuntimeSubgraphState(TypedDict, total=False):
    tenant_id:str; user_id:str; correlation_id:str; input:dict[str,Any]; completed_nodes:list[str]; runtime_evidence:dict[str,Any]; agent_outputs:dict[str,Any]; evidence_ids:list[str]; last_error:dict[str,Any]; errors:list[dict[str,Any]]; graph_budget:dict[str,Any]
class RCASubgraphState(TypedDict, total=False):
    tenant_id:str; user_id:str; correlation_id:str; input:dict[str,Any]; completed_nodes:list[str]; fused_evidence:dict[str,Any]; rca_result:dict[str,Any]; agent_outputs:dict[str,Any]; last_error:dict[str,Any]; errors:list[dict[str,Any]]; graph_budget:dict[str,Any]


def _request(state: GraphExecutionState) -> AgentRequest:
    source = state.get("input", {})
    context = dict(source.get("context", {}))
    context["graph_version"] = state.get("graph_version", GRAPH_VERSION)
    return AgentRequest(tenant_id=UUID(state["tenant_id"]), user_id=state["user_id"], correlation_id=state["correlation_id"], objective=str(source["query"]), context=context)


def _auth(request: AgentRequest) -> AgentAuthorization:
    return AgentAuthorization(tenant_id=request.tenant_id, user_id=request.user_id, allowed_permissions=frozenset(ToolPermission))


def _text(item: Any, tenant_id: UUID) -> NormalizedEvidence:
    content = item.content.strip(); score = min(1.0, max(0.0, float(item.score)))
    return NormalizedEvidence(evidence_id=item.evidence_id, tenant_id=tenant_id, channel=EvidenceChannel.TEXT, source_system="rag", source_id=str(item.chunk_id), source_key=item.source_key, title=item.title, content=content, content_hash=sha256(content.encode()).hexdigest(), relevance_score=score, source_confidence=.9, fusion_score=score, locator=EvidenceLocator(document_id=item.document_id, chunk_id=item.chunk_id), estimated_tokens=max(1, len(content)//4), provenance={"document_kind": item.document_kind.value,"chunk_id":str(item.chunk_id)})


def _github(item: Any, tenant_id: UUID, index: int) -> NormalizedEvidence:
    content=item.statement.strip(); marker=":".join(item.source_call_ids); evidence_id=uuid5(NAMESPACE_URL,f"{tenant_id}:github:{index}:{marker}:{content}")
    return NormalizedEvidence(evidence_id=evidence_id,tenant_id=tenant_id,channel=EvidenceChannel.TEXT,source_system="github",source_id=marker or str(index),source_key=f"github:{marker or index}",title="Repository change evidence",content=content,content_hash=sha256(content.encode()).hexdigest(),relevance_score=.85,source_confidence=.9,fusion_score=.85,locator=EvidenceLocator(),estimated_tokens=max(1,len(content)//4),provenance={"source_call_ids":item.source_call_ids})


def _visual(item: Any, tenant_id: UUID) -> NormalizedEvidence:
    content=item.summary.strip(); score=item.confidence_score
    return NormalizedEvidence(evidence_id=item.evidence_id,tenant_id=tenant_id,channel=EvidenceChannel.VISUAL,source_system="visual_evidence",source_id=str(item.page_id),source_key=f"visual:{item.document_id}:{item.page_number}",title=f"Visual page {item.page_number}",content=content,content_hash=sha256(content.encode()).hexdigest(),relevance_score=score,source_confidence=score,fusion_score=score,locator=EvidenceLocator(document_id=item.document_id,page_id=item.page_id,page_number=item.page_number),estimated_tokens=max(1,len(content)//4),image_cost=1,provenance={"analysis_type":item.analysis_type.value})


def _runtime(item: Any) -> NormalizedEvidence:
    content=item.content.strip(); score=min(1.0,item.relevance_score*item.source_confidence)
    return NormalizedEvidence(evidence_id=item.evidence_id,tenant_id=item.tenant_id,channel=EvidenceChannel.RUNTIME,source_system=item.source_system,source_id=item.source_id,source_key=f"runtime:{item.source_system}:{item.source_id}",title=item.title,content=content,content_hash=sha256(content.encode()).hexdigest(),relevance_score=item.relevance_score,source_confidence=item.source_confidence,fusion_score=score,locator=EvidenceLocator(timestamp=item.observed_at),estimated_tokens=max(1,len(content)//4),provenance={"service":item.service,"environment":item.environment,"kind":item.kind.value})


def incident_rca_definition(agents: IncidentAgentBundle) -> GraphDefinition:
    def build(checkpointer: Any) -> Any:
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import RetryPolicy

        async def budget_init(s):
            now=datetime.now(timezone.utc).isoformat()
            return {"graph_budget":{"started_at":now,"steps":0,"llm_calls":0,"tool_calls":0,"critic_loops":0,"rag_rewrites":0,"context_tokens":0,"estimated_cost_usd":0.0}}

        async def supervisor(s):
            q=_request(s); x=await agents.supervisor.run(q,authorization=_auth(q)); v=x.model_dump(mode="json"); return {"supervisor_decision":v,"agent_outputs":{"supervisor":v}}
        async def supervisor_route_accept(s):
            decision=s["supervisor_decision"]
            return {"supervisor_route_state":{"mode":"accepted","route":decision["route"],"confidence":decision["confidence"],"requires_validation":False}}
        async def supervisor_route_validate(s):
            decision=s["supervisor_decision"]
            return {"supervisor_route_state":{"mode":"planner_validation","route":decision["route"],"confidence":decision["confidence"],"requires_validation":True}}
        async def supervisor_route_fallback(s):
            decision=s["supervisor_decision"]
            return {"supervisor_route_state":{"mode":"deterministic_fallback","route":"planning","original_route":decision["route"],"confidence":decision["confidence"],"requires_validation":True},"approval_state":{"required":True,"status":"CLARIFICATION_REQUIRED","reason_codes":["low_supervisor_confidence"]}}
        async def planning(s):
            q=_request(s); x=await agents.planning.run(q,authorization=_auth(q),max_total_tool_calls=agents.settings.agent_max_plan_tool_calls); v=x.model_dump(mode="json"); return {"plan":v,"agent_outputs":{"planning":v}}
        async def github(s):
            q=_request(s); x=await agents.github.run(q,authorization=_auth(q),budget=ToolBudget(max_calls=agents.settings.agent_default_tool_budget)); v=x.model_dump(mode="json"); return {"github_evidence":v,"agent_outputs":{"github":v}}
        async def rag(s):
            q=_request(s); x=await agents.rag.run(q,authorization=_auth(q),budget=ToolBudget(max_calls=agents.settings.rag_agent_tool_budget),model_name=agents.settings.openai_embedding_model,dimensions=agents.settings.openai_embedding_dimensions,candidate_k=agents.settings.retrieval_candidate_k,min_evidence=agents.settings.rag_agent_min_evidence,min_sources=agents.settings.rag_agent_min_sources); v=x.model_dump(mode="json"); return {"rag_evidence":v,"agent_outputs":{"rag":v},"evidence_ids":[str(i.evidence_id) for i in x.evidence]}
        async def visual(s):
            q=_request(s); x=await agents.visual_evidence.run(q,authorization=_auth(q),budget=ToolBudget(max_calls=agents.settings.visual_agent_tool_budget),min_short_side=agents.settings.visual_agent_min_short_side,min_confidence=agents.settings.visual_agent_min_confidence,max_analyses=agents.settings.visual_agent_max_analyses); v=x.model_dump(mode="json"); return {"visual_evidence":v,"agent_outputs":{"visual_evidence":v},"evidence_ids":[str(i.evidence_id) for i in x.evidence]}
        async def runtime(s):
            q=_request(s); x=await agents.runtime_evidence.run(q,authorization=_auth(q),budget=ToolBudget(max_calls=agents.settings.runtime_agent_tool_budget),min_evidence=agents.settings.runtime_agent_min_evidence,min_successful_sources=agents.settings.runtime_agent_min_sources,anomaly_z_threshold=agents.settings.runtime_anomaly_z_threshold,anomaly_percent_threshold=agents.settings.runtime_anomaly_percent_threshold); v=x.model_dump(mode="json"); return {"runtime_evidence":v,"agent_outputs":{"runtime_evidence":v},"evidence_ids":[str(i.evidence_id) for i in x.evidence]}
        async def fuse(s):
            from verideploy.agents.contracts import GitHubAgentResult
            from verideploy.agents.rag import RAGAgentResult
            from verideploy.agents.runtime import RuntimeEvidenceAgentResult
            from verideploy.agents.visual import VisualEvidenceAgentResult
            tenant=UUID(s["tenant_id"]); g=GitHubAgentResult.model_validate(s["github_evidence"]); r=RAGAgentResult.model_validate(s["rag_evidence"]); v=VisualEvidenceAgentResult.model_validate(s["visual_evidence"]); t=RuntimeEvidenceAgentResult.model_validate(s["runtime_evidence"])
            items=[*(_github(i,tenant,n) for n,i in enumerate(g.findings,1)),*(_text(i,tenant) for i in r.evidence),*(_visual(i,tenant) for i in v.evidence),*(_runtime(i) for i in t.evidence)]; unique={str(i.evidence_id):i for i in items}; value={"evidence":[i.model_dump(mode="json") for i in unique.values()]}; return {"fused_evidence":value,"node_outputs":{"fuse_evidence":value},"evidence_ids":list(unique)}
        async def rca(s):
            from verideploy.agents.rca import RCAAgentResult
            q=_request(s); evidence=[NormalizedEvidence.model_validate(i) for i in s["fused_evidence"]["evidence"]]; x=await agents.rca.run(q,authorization=_auth(q),evidence=evidence,min_root_support=agents.settings.rca_agent_min_root_support,min_root_confidence=agents.settings.rca_agent_min_confidence,max_evidence=agents.settings.rca_agent_max_evidence); v=x.model_dump(mode="json"); return {"rca_result":v,"agent_outputs":{"rca":v}}
        async def critic(s):
            from verideploy.agents.rca import RCAAgentResult
            q=_request(s); evidence=[NormalizedEvidence.model_validate(i) for i in s["fused_evidence"]["evidence"]]; r=RCAAgentResult.model_validate(s["rca_result"]); x=await agents.critic.run(q,authorization=_auth(q),rca=r,evidence=evidence,budget=ToolBudget(max_calls=agents.settings.critic_agent_tool_budget),entailment_threshold=agents.settings.critic_entailment_threshold,partial_threshold=agents.settings.critic_partial_entailment_threshold,pass_confidence=agents.settings.critic_pass_confidence,max_followups=agents.settings.critic_max_followups,followup_top_k=agents.settings.critic_followup_top_k,model_name=agents.settings.openai_embedding_model,dimensions=agents.settings.openai_embedding_dimensions,candidate_k=agents.settings.retrieval_candidate_k); v=x.model_dump(mode="json"); approval={"required":x.human_escalation.required,"reason_codes":x.human_escalation.reason_codes,"status":"PENDING" if x.human_escalation.required else "NOT_REQUIRED"}; return {"critic_result":v,"approval_state":approval,"agent_outputs":{"critic":v}}
        async def verify_claims(s):
            from verideploy.agents.rag import RAGAgentResult
            from verideploy.agents.rca import RCAAgentResult
            from verideploy.rag.hallucination.schemas import HallucinationProtectionRequest, ProposedClaim
            rag_result=RAGAgentResult.model_validate(s["rag_evidence"]); rca_result=RCAAgentResult.model_validate(s["rca_result"])
            if not rag_result.retrieval_traces: raise ValueError("claim verification requires a persisted self-corrective RAG run")
            normalized={str(i["evidence_id"]):i for i in s["fused_evidence"]["evidence"]}
            claims=[]
            for item in rca_result.hypotheses:
                chunk_ids=[]
                for evidence_id in item.supporting_evidence_ids:
                    raw=normalized.get(str(evidence_id)); chunk=(raw or {}).get("provenance",{}).get("chunk_id")
                    if chunk: chunk_ids.append(UUID(chunk))
                claims.append(ProposedClaim(claim_id=item.hypothesis_id,text=item.statement,evidence_chunk_ids=tuple(chunk_ids),material=item.kind.value=="root_cause",proposed_confidence=item.adjusted_confidence))
            result=agents.claim_verifier.protect(HallucinationProtectionRequest(tenant_id=UUID(s["tenant_id"]),self_corrective_run_id=rag_result.retrieval_traces[0].trace_id,claims=claims))
            value=result.model_dump(mode="json")
            return {"claim_verification":value,"node_outputs":{"hallucination_protection":value}}
        async def validate_citations(s):
            from verideploy.rag.citations.schemas import CitationBuildRequest
            verification=s.get("claim_verification") or {}
            if not verification.get("protected") or not verification.get("verification_id"):
                raise ValueError("citation validation requires protected hallucination-verification output")
            bundle=agents.citation_service.build_from_verification(CitationBuildRequest(tenant_id=UUID(s["tenant_id"]),verification_id=UUID(verification["verification_id"])))
            if bundle.final_claim_count and not (bundle.final_claims_cited and bundle.all_citations_entail):
                raise ValueError("final RCA citation closure failed")
            value=bundle.model_dump(mode="json"); ids=[str(x.citation_id) for x in bundle.citations]
            return {"citation_validation":value,"citation_ids":ids,"node_outputs":{"citation_validation":value}}
        async def approval(s):
            from langgraph.types import interrupt
            from verideploy.approvals.schemas import ApprovalRequestCreate, ApprovalRisk, EvidenceSummary, ReviewPolicy
            source=s.get("input",{}); action=dict(source.get("remediation_action") or {})
            required=bool(action.get("consequential")) or bool(s["approval_state"].get("required"))
            if not required: return {"approval_state":{"required":False,"status":"NOT_REQUIRED"}}
            evidence=[str(i) for i in s.get("evidence_ids",[])]; risk_enum=ApprovalRisk(str(action.get("risk") or "high"))
            if s["approval_state"].get("required") and risk_enum in {ApprovalRisk.LOW,ApprovalRisk.MEDIUM}: risk_enum=ApprovalRisk.HIGH
            risk=risk_enum.value; risk_score={ApprovalRisk.LOW:25,ApprovalRisk.MEDIUM:55,ApprovalRisk.HIGH:80,ApprovalRisk.CRITICAL:100}[risk_enum]
            request=agents.approval_service.request_review(ApprovalRequestCreate(tenant_id=UUID(s["tenant_id"]),run_id=UUID(s["run_id"]),investigation_id=s["investigation_id"],action_type=str(action.get("action") or "proposed_remediation"),action_payload=action,risk=risk_enum,risk_score=risk_score,requested_by=s["user_id"],evidence_summary=EvidenceSummary(title="Consequential remediation review",summary=str(action.get("summary") or "Review evidence and dry-run before execution."),evidence_ids=tuple(evidence),citation_ids=tuple(s.get("citation_ids",[])),risk_factors=tuple(s["approval_state"].get("reason_codes",[]))),policy=ReviewPolicy(policy_id="incident-remediation-v1"),idempotency_key=f"{s['run_id']}:remediation"))
            decision=interrupt({"approval_id":str(request.approval_id),"action":action.get("action") or "proposed_remediation","evidence":evidence,"risk":risk,"dry_run":action.get("dry_run") or {},"run_id":s["run_id"],"investigation_id":s["investigation_id"]})
            if not isinstance(decision,dict) or decision.get("decision") not in {"approve","reject"}: raise ValueError("approval resume must contain decision=approve|reject")
            return {"approval_state":{"required":True,"approval_id":str(request.approval_id),"status":"APPROVED" if decision["decision"]=="approve" else "REJECTED","decision":decision["decision"],"reviewer_id":decision.get("reviewer_id"),"comment":decision.get("comment")},"approval_ids":[str(request.approval_id)]}
        async def finalize(s):
            from verideploy.agents.critic import CriticAgentResult
            from verideploy.agents.rca import RCAAgentResult
            r=RCAAgentResult.model_validate(s["rca_result"]); c=CriticAgentResult.model_validate(s["critic_result"]); verification=s["claim_verification"]; citation_validation=s.get("citation_validation") or {}; top=next((i for i in r.hypotheses if i.hypothesis_id==r.sufficiency.top_hypothesis_id),r.hypotheses[0] if r.hypotheses else None); evidence_ids=[str(i) for i in (top.supporting_evidence_ids if top else [])]; citations=list(s.get("citation_ids",[])); approved=s["approval_state"].get("status") not in {"REJECTED","PENDING"}; citation_closed=bool(citation_validation) and citation_validation.get("final_claims_cited") and citation_validation.get("all_citations_entail"); final={"summary":verification["protected_answer"],"hypothesis_id":top.hypothesis_id if top else None,"confidence":c.adjusted_root_cause_confidence,"determined":r.sufficiency.root_cause_determined and c.passed and verification["protected"] and citation_closed and approved,"evidence_ids":evidence_ids,"citation_ids":citations,"alternatives":[i.model_dump(mode="json") for i in r.alternatives],"approval_state":s["approval_state"],"verification_id":verification["verification_id"],"citation_validation":citation_validation}; return {"status":"COMPLETED","final_answer":final,"final_output":final,"citation_ids":citations}

        async def planner_repair(s):
            failure=s["last_error"]; q=_request(s).model_copy(update={"objective":f"Repair the failed {failure['node']} step. {failure['message']}"})
            repaired=await agents.planning.run(q,authorization=_auth(q),max_total_tool_calls=agents.settings.agent_max_plan_tool_calls)
            value=repaired.model_dump(mode="json")
            return {"recovery":{"planner_repair":{"failure":failure,"plan":value}},"agent_outputs":{"planner_repair":value}}

        async def rag_rewrite(s):
            q=_request(s).model_copy(update={"objective":f"{_request(s).objective} Find corroborating operational evidence and alternative terminology."})
            x=await agents.rag.run(q,authorization=_auth(q),budget=ToolBudget(max_calls=agents.settings.rag_agent_tool_budget),model_name=agents.settings.openai_embedding_model,dimensions=agents.settings.openai_embedding_dimensions,candidate_k=agents.settings.retrieval_candidate_k,min_evidence=agents.settings.rag_agent_min_evidence,min_sources=agents.settings.rag_agent_min_sources)
            value=x.model_dump(mode="json")
            return {"rag_evidence":value,"recovery":{"rag_rewrite":{"attempt":int(s.get("retry_count",0))+1,"sufficient":x.sufficiency.sufficient}},"agent_outputs":{"rag_rewrite":value},"retry_count":int(s.get("retry_count",0))+1,"last_error":{},"evidence_ids":[str(i.evidence_id) for i in x.evidence]}

        async def human_review_error(s):
            from langgraph.types import interrupt
            decision=interrupt({"action":"review_failed_critic","risk":"high","dry_run":{},"evidence":list(s.get("evidence_ids",[])),"failure":s["last_error"],"run_id":s["run_id"]})
            return {"approval_state":{"required":True,"status":"APPROVED" if isinstance(decision,dict) and decision.get("decision")=="approve" else "REJECTED","decision":decision.get("decision") if isinstance(decision,dict) else "reject"},"recovery":{"critic_review":s["last_error"]}}

        async def safe_terminate(s):
            failure=s["last_error"]; final={"summary":"The workflow stopped safely because authorization or safety policy denied the operation.","determined":False,"confidence":0.0,"evidence_ids":list(s.get("evidence_ids",[])),"citation_ids":list(s.get("citation_ids",[])),"error":failure,"escalation_required":False}
            return {"status":"COMPLETED","final_answer":final,"final_output":final,"recovery":{"safe_termination":failure}}

        async def degraded_finalize(s):
            failure=s["last_error"]; final={"summary":"A complete RCA could not be produced. Available evidence is preserved for human investigation.","determined":False,"confidence":0.0,"evidence_ids":list(s.get("evidence_ids",[])),"citation_ids":list(s.get("citation_ids",[])),"error":failure,"escalation_required":True}
            return {"status":"COMPLETED","final_answer":final,"final_output":final,"approval_state":{"required":True,"status":"ESCALATED"},"recovery":{"degraded_result":failure}}

        def guarded(name,fn):
            deterministic=DeterministicNodeWrapper(name,fn,timeout_seconds=120)
            async def call(state):
                try:
                    budget=dict(state.get("graph_budget") or {})
                    started=datetime.fromisoformat(str(budget.get("started_at") or datetime.now(timezone.utc).isoformat()).replace("Z","+00:00"))
                    llm_nodes={"supervisor","planning","planner_repair","github","rag","rag_rewrite","visual_evidence","runtime_evidence","rca"}
                    steps=int(budget.get("steps",0))+1; llm=int(budget.get("llm_calls",0))+(1 if name in llm_nodes else 0)
                    critic_loops=int(budget.get("critic_loops",0))+(1 if name=="critic" else 0)
                    rag_rewrites=int(budget.get("rag_rewrites",0))+(1 if name=="rag_rewrite" else 0)
                    context_tokens=max(int(budget.get("context_tokens",0)),len(json.dumps(state.get("fused_evidence",{}),default=str))//4)
                    estimated_cost=float(budget.get("estimated_cost_usd",0.0))+(float(agents.settings.ai_default_estimated_request_cost_usd) if name in llm_nodes else 0.0)
                    elapsed=(datetime.now(timezone.utc)-started).total_seconds()
                    limits=((steps,agents.settings.graph_max_steps,"steps"),(llm,agents.settings.graph_max_llm_calls,"llm_calls"),(critic_loops,agents.settings.graph_max_critic_loops,"critic_loops"),(rag_rewrites,agents.settings.graph_max_rag_rewrites,"rag_rewrites"),(context_tokens,agents.settings.graph_max_context_tokens,"context_tokens"),(elapsed,agents.settings.graph_max_wall_time_seconds,"wall_time"),(estimated_cost,float(agents.settings.graph_max_cost_usd),"cost"))
                    exceeded=[label for value,limit,label in limits if value>limit]
                    if exceeded: raise GraphBudgetExceeded("graph budget exceeded: "+",".join(exceeded))
                    result=await deterministic(state)
                    tool_calls=0
                    for output in result.get("agent_outputs",{}).values():
                        if isinstance(output,dict): tool_calls+=int(output.get("tool_calls_used",0))
                    total_tools=int(budget.get("tool_calls",0))+tool_calls
                    if total_tools>agents.settings.graph_max_tool_calls: raise GraphBudgetExceeded("graph budget exceeded: tool_calls")
                    result["graph_budget"]={**budget,"started_at":started.isoformat(),"steps":steps,"llm_calls":llm,"tool_calls":total_tools,"critic_loops":critic_loops,"rag_rewrites":rag_rewrites,"context_tokens":context_tokens,"estimated_cost_usd":round(estimated_cost,6)}
                    result["last_error"]={}; return result
                except Exception as exc:
                    if retry_transient(exc): raise
                    failure=error_state(name,exc)
                    return {"last_error":failure,"errors":[failure]}
            return call

        def route(next_node):
            def choose(state):
                failure=state.get("last_error") or {}
                if not failure:
                    if next_node=="visual_evidence" and state.get("rag_evidence") and not state["rag_evidence"].get("sufficiency",{}).get("sufficient",False) and int(state.get("retry_count",0))<agents.settings.graph_max_rag_rewrites: return "rag_rewrite"
                    return next_node
                category=FailureClass(failure["category"])
                if category in {FailureClass.AUTHORIZATION,FailureClass.PROMPT_INJECTION,FailureClass.FATAL}: return "safe_terminate"
                if category is FailureClass.CRITIC_FAILURE: return "human_review_error"
                if category is FailureClass.INSUFFICIENT_EVIDENCE and failure.get("node")=="rag" and int(state.get("retry_count",0))<agents.settings.graph_max_rag_rewrites: return "rag_rewrite"
                if category in {FailureClass.LLM_RECOVERABLE,FailureClass.USER_FIXABLE}: return "planner_repair"
                return "degraded_finalize"
            return choose

        functions={"supervisor":supervisor,"planning":planning,"github":github,"rag":rag,"visual_evidence":visual,"runtime_evidence":runtime,"fuse_evidence":fuse,"rca":rca,"critic":critic,"verify_claims":verify_claims,"validate_citations":validate_citations,"approval":approval,"finalize":finalize}; graph=StateGraph(GraphExecutionState)
        llm_policy=RetryPolicy(initial_interval=.5,backoff_factor=2,max_interval=8,max_attempts=4,jitter=True,retry_on=retry_transient)
        tool_policy=RetryPolicy(initial_interval=1,backoff_factor=2,max_interval=10,max_attempts=3,jitter=True,retry_on=retry_transient)
        policies={"github":tool_policy,"runtime_evidence":tool_policy,"fuse_evidence":tool_policy,"verify_claims":tool_policy,"validate_citations":tool_policy}
        specialist_schemas={"github":GitHubSubgraphState,"rag":RAGSubgraphState,"visual_evidence":VisualSubgraphState,"runtime_evidence":RuntimeSubgraphState,"rca":RCASubgraphState}
        for name,fn in functions.items():
            if name in specialist_schemas:
                sub=StateGraph(specialist_schemas[name]); sub.add_node("execute",guarded(name,fn),retry_policy=policies.get(name,llm_policy)); sub.add_edge(START,"execute"); sub.add_edge("execute",END)
                graph.add_node(name,sub.compile())
            else: graph.add_node(name,guarded(name,fn),retry_policy=policies.get(name,llm_policy))
        graph.add_node("budget_init",budget_init)
        graph.add_node("supervisor_route_accept",guarded("supervisor_route_accept",supervisor_route_accept)); graph.add_node("supervisor_route_validate",guarded("supervisor_route_validate",supervisor_route_validate)); graph.add_node("supervisor_route_fallback",guarded("supervisor_route_fallback",supervisor_route_fallback))
        graph.add_node("planner_repair",guarded("planner_repair",planner_repair),retry_policy=llm_policy); graph.add_node("rag_rewrite",guarded("rag_rewrite",rag_rewrite),retry_policy=llm_policy); graph.add_node("human_review_error",human_review_error); graph.add_node("safe_terminate",safe_terminate); graph.add_node("degraded_finalize",degraded_finalize)
        graph.add_edge(START,"budget_init"); graph.add_edge("budget_init",AGENT_SEQUENCE[0])
        destinations={name:name for name in (*AGENT_SEQUENCE,"planner_repair","rag_rewrite","human_review_error","safe_terminate","degraded_finalize")}
        def supervisor_confidence(state):
            confidence=float(state["supervisor_decision"]["confidence"])
            if confidence>=.80: return "accept"
            if confidence>=.55: return "validate"
            return "fallback"
        graph.add_conditional_edges("supervisor",supervisor_confidence,{"accept":"supervisor_route_accept","validate":"supervisor_route_validate","fallback":"supervisor_route_fallback"})
        graph.add_edge("supervisor_route_accept","planning"); graph.add_edge("supervisor_route_validate","planning"); graph.add_edge("supervisor_route_fallback","planning")
        for a,b in zip(AGENT_SEQUENCE[1:],AGENT_SEQUENCE[2:]): graph.add_conditional_edges(a,route(b),destinations)
        def route_final(state):
            if not state.get("last_error"): return "complete"
            failure=FailureClass(state["last_error"]["category"])
            if failure in {FailureClass.AUTHORIZATION,FailureClass.PROMPT_INJECTION,FailureClass.FATAL}: return "safe_terminate"
            if failure is FailureClass.CRITIC_FAILURE: return "human_review_error"
            if failure in {FailureClass.LLM_RECOVERABLE,FailureClass.USER_FIXABLE}: return "planner_repair"
            return "degraded_finalize"
        graph.add_conditional_edges(AGENT_SEQUENCE[-1],route_final,{"complete":END,"degraded_finalize":"degraded_finalize","planner_repair":"planner_repair","safe_terminate":"safe_terminate","human_review_error":"human_review_error"})
        graph.add_edge("planner_repair","degraded_finalize"); graph.add_edge("rag_rewrite","visual_evidence"); graph.add_edge("human_review_error","degraded_finalize"); graph.add_edge("safe_terminate",END); graph.add_edge("degraded_finalize",END)
        return graph.compile(checkpointer=checkpointer)
    return GraphDefinition(name="incident_rca",version="2.0.0",factory=build,description="In-process eight-agent incident RCA workflow with evidence fusion and critic finalization.")
