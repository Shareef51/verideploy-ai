from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from services.ai.agents import get_planning_agent, get_rag_agent, get_supervisor_agent, get_visual_evidence_agent, get_runtime_evidence_agent, get_rca_agent, get_critic_agent
from verideploy.agents.contracts import AgentAuthorization, AgentPlan, AgentRequest, SupervisorDecision, ToolPermission
from verideploy.agents.planner import PlanningAgent
from verideploy.agents.rag import RAGAgent, RAGAgentResult
from verideploy.agents.supervisor import SupervisorAgent
from verideploy.agents.visual import VisualEvidenceAgent, VisualEvidenceAgentResult
from verideploy.agents.runtime import RuntimeEvidenceAgent, RuntimeEvidenceAgentResult
from verideploy.agents.rca import RCAAgent, RCAAgentResult
from verideploy.agents.critic import CriticAgent, CriticAgentResult
from verideploy.rag.fusion.schemas import EvidenceChannel, NormalizedEvidence
from verideploy.agents.contracts import ToolBudget
from verideploy.config import get_settings

router = APIRouter(prefix="/internal/v1/agents", tags=["agents-internal"])


class AgentInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: AgentRequest
    permissions: list[ToolPermission] = Field(default_factory=list, max_length=32)


def _authorize(service_name: str) -> None:
    if service_name not in {"verideploy-gateway", "verideploy-investigation-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


def _auth(payload: AgentInvocation, tenant_id: UUID, user_id: str) -> AgentAuthorization:
    if payload.request.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope mismatch")
    if payload.request.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user scope mismatch")
    return AgentAuthorization(tenant_id=tenant_id, user_id=user_id, allowed_permissions=frozenset(payload.permissions))


@router.post("/supervise", response_model=SupervisorDecision)
async def supervise(
    payload: AgentInvocation,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(),
    x_user_id: str = Header(),
    agent: SupervisorAgent = Depends(get_supervisor_agent),
) -> SupervisorDecision:
    _authorize(x_internal_service)
    return await agent.run(payload.request, authorization=_auth(payload, x_tenant_id, x_user_id))


@router.post("/plan", response_model=AgentPlan)
async def plan(
    payload: AgentInvocation,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(),
    x_user_id: str = Header(),
    agent: PlanningAgent = Depends(get_planning_agent),
) -> AgentPlan:
    _authorize(x_internal_service)
    settings = get_settings()
    return await agent.run(payload.request, authorization=_auth(payload, x_tenant_id, x_user_id), max_total_tool_calls=settings.agent_max_plan_tool_calls)


@router.post("/rag", response_model=RAGAgentResult)
async def rag(
    payload: AgentInvocation,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(),
    x_user_id: str = Header(),
    agent: RAGAgent = Depends(get_rag_agent),
) -> RAGAgentResult:
    _authorize(x_internal_service)
    settings = get_settings()
    return await agent.run(
        payload.request,
        authorization=_auth(payload, x_tenant_id, x_user_id),
        budget=ToolBudget(max_calls=settings.rag_agent_tool_budget),
        model_name=settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimensions,
        candidate_k=settings.retrieval_candidate_k,
        min_evidence=settings.rag_agent_min_evidence,
        min_sources=settings.rag_agent_min_sources,
    )


@router.post("/visual-evidence", response_model=VisualEvidenceAgentResult)
async def visual_evidence(
    payload: AgentInvocation,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(),
    x_user_id: str = Header(),
    agent: VisualEvidenceAgent = Depends(get_visual_evidence_agent),
) -> VisualEvidenceAgentResult:
    _authorize(x_internal_service)
    settings = get_settings()
    return await agent.run(
        payload.request,
        authorization=_auth(payload, x_tenant_id, x_user_id),
        budget=ToolBudget(max_calls=settings.visual_agent_tool_budget),
        min_short_side=settings.visual_agent_min_short_side,
        min_confidence=settings.visual_agent_min_confidence,
        max_analyses=settings.visual_agent_max_analyses,
    )


@router.post("/runtime-evidence", response_model=RuntimeEvidenceAgentResult)
async def runtime_evidence(
    payload: AgentInvocation,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(),
    x_user_id: str = Header(),
    agent: RuntimeEvidenceAgent = Depends(get_runtime_evidence_agent),
) -> RuntimeEvidenceAgentResult:
    _authorize(x_internal_service)
    settings = get_settings()
    return await agent.run(
        payload.request, authorization=_auth(payload, x_tenant_id, x_user_id),
        budget=ToolBudget(max_calls=settings.runtime_agent_tool_budget),
        min_evidence=settings.runtime_agent_min_evidence, min_successful_sources=settings.runtime_agent_min_sources,
        anomaly_z_threshold=settings.runtime_anomaly_z_threshold, anomaly_percent_threshold=settings.runtime_anomaly_percent_threshold,
    )


class RCAInvocation(AgentInvocation):
    evidence: list[NormalizedEvidence] = Field(min_length=1, max_length=64)
    required_channels: list[EvidenceChannel] = Field(default_factory=list, max_length=3)


@router.post("/rca", response_model=RCAAgentResult)
async def rca(
    payload: RCAInvocation,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(),
    x_user_id: str = Header(),
    agent: RCAAgent = Depends(get_rca_agent),
) -> RCAAgentResult:
    _authorize(x_internal_service)
    settings = get_settings()
    return await agent.run(
        payload.request,
        authorization=_auth(payload, x_tenant_id, x_user_id),
        evidence=payload.evidence,
        min_root_support=settings.rca_agent_min_root_support,
        min_root_confidence=settings.rca_agent_min_confidence,
        required_channels=payload.required_channels,
        max_evidence=settings.rca_agent_max_evidence,
    )


class CriticInvocation(AgentInvocation):
    rca: RCAAgentResult
    evidence: list[NormalizedEvidence] = Field(min_length=1, max_length=128)


@router.post("/critic", response_model=CriticAgentResult)
async def critic(
    payload: CriticInvocation,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(),
    x_user_id: str = Header(),
    agent: CriticAgent = Depends(get_critic_agent),
) -> CriticAgentResult:
    _authorize(x_internal_service)
    settings = get_settings()
    return await agent.run(
        payload.request,
        authorization=_auth(payload, x_tenant_id, x_user_id),
        rca=payload.rca,
        evidence=payload.evidence,
        budget=ToolBudget(max_calls=settings.critic_agent_tool_budget),
        entailment_threshold=settings.critic_entailment_threshold,
        partial_threshold=settings.critic_partial_entailment_threshold,
        pass_confidence=settings.critic_pass_confidence,
        max_followups=settings.critic_max_followups,
        followup_top_k=settings.critic_followup_top_k,
        model_name=settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimensions,
        candidate_k=settings.retrieval_candidate_k,
    )
