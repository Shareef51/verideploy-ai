from __future__ import annotations

from functools import lru_cache

from services.ai.ai_gateway import get_ai_gateway
from verideploy.agents.factory import create_agent_runtime_components
from verideploy.agents.planner import PlanningAgent
from verideploy.agents.rag import RAGAgent
from verideploy.agents.rag_tools import ProductionRAGTool
from verideploy.agents.runtime import RuntimeEvidenceAgent
from verideploy.agents.rca import RCAAgent
from verideploy.agents.critic import CriticAgent, HybridCriticFollowupRetrieval, StructuredSemanticClaimGrader
from verideploy.agents.runtime_tools import LiveRuntimeEndpoints, LiveRuntimeTool, RuntimeSource, SyntheticRuntimeTool
from verideploy.config import get_settings
from verideploy.agents.supervisor import SupervisorAgent
from verideploy.agents.github import GitHubAgent
from verideploy.integrations.factory import create_engineering_integrations
from verideploy.graphs.incident_rca_v2 import IncidentAgentBundle
from services.ai.self_corrective_rag import get_self_corrective_rag
from services.ai.hallucination_protection import get_hallucination_protector
from services.ai.approvals import get_approval_service
from services.ai.citations import get_citation_service


class _GitHubAgentTool:
    def __init__(self, backend): self.backend = backend

    async def invoke(self, operation: str, arguments: dict[str, str]) -> dict:
        owner, repo = arguments["owner"], arguments["repo"]
        if operation == "repository.get": return await self.backend.repository_get(owner, repo)
        if operation == "pull_request.get": return await self.backend.pull_request_get(owner, repo, int(arguments["number"]))
        path = f"/repos/{owner}/{repo}/commits/{arguments['sha']}" if operation == "commit.get" else f"/repos/{owner}/{repo}/actions/runs/{arguments['run_id']}"
        response = await self.backend.client.request("GET", path, budget=self.backend.client.new_budget())
        value = response.json()
        return value if isinstance(value, dict) else {"items": value}


@lru_cache
def get_supervisor_agent() -> SupervisorAgent:
    model, prompts, repository = create_agent_runtime_components(gateway=get_ai_gateway())
    return SupervisorAgent(model=model, prompts=prompts, repository=repository)


@lru_cache
def get_planning_agent() -> PlanningAgent:
    model, prompts, repository = create_agent_runtime_components(gateway=get_ai_gateway())
    return PlanningAgent(model=model, prompts=prompts, repository=repository)


@lru_cache
def get_github_agent() -> GitHubAgent:
    model, prompts, repository = create_agent_runtime_components(gateway=get_ai_gateway())
    backend = create_engineering_integrations(get_settings()).github
    return GitHubAgent(model=model, prompts=prompts, repository=repository, tools=_GitHubAgentTool(backend))


@lru_cache
def get_rag_agent() -> RAGAgent:
    model, prompts, repository = create_agent_runtime_components(gateway=get_ai_gateway())
    return RAGAgent(
        model=model,
        prompts=prompts,
        repository=repository,
        retrieval=_production_rag_tool(),
    )


@lru_cache
def get_visual_evidence_agent():
    from services.ai.image_intelligence import get_image_intelligence_service
    from services.ai.visual_retrieval import get_visual_retrieval_service
    from verideploy.agents.visual import VisualEvidenceAgent
    from verideploy.agents.visual_tools import StoredVisualAnalysisTool, VisualDocumentSearchTool
    model, prompts, repository = create_agent_runtime_components(gateway=get_ai_gateway())
    return VisualEvidenceAgent(
        model=model,
        prompts=prompts,
        repository=repository,
        search=VisualDocumentSearchTool(get_visual_retrieval_service()),
        analyzer=StoredVisualAnalysisTool(get_image_intelligence_service()),
    )


@lru_cache
def get_runtime_evidence_agent() -> RuntimeEvidenceAgent:
    model, prompts, repository = create_agent_runtime_components(gateway=get_ai_gateway())
    settings = get_settings()
    if settings.runtime_evidence_adapter == "live":
        endpoints = LiveRuntimeEndpoints(
            prometheus_url=settings.prometheus_base_url, grafana_url=settings.grafana_base_url,
            tempo_url=settings.tempo_base_url, loki_url=settings.loki_base_url,
            bearer_token=settings.runtime_observability_token.get_secret_value() if settings.runtime_observability_token else None,
        )
        tools = {source: LiveRuntimeTool(source, endpoints, timeout_seconds=settings.runtime_http_timeout_seconds) for source in RuntimeSource}
    else:
        tools = {source: SyntheticRuntimeTool(source) for source in RuntimeSource}
    return RuntimeEvidenceAgent(model=model, prompts=prompts, repository=repository, tools=tools)


@lru_cache
def get_rca_agent() -> RCAAgent:
    model, prompts, repository = create_agent_runtime_components(gateway=get_ai_gateway())
    return RCAAgent(model=model, prompts=prompts, repository=repository)


@lru_cache
def get_critic_agent() -> CriticAgent:
    model, prompts, repository = create_agent_runtime_components(gateway=get_ai_gateway())
    return CriticAgent(
        model=model, prompts=prompts, repository=repository,
        followup=HybridCriticFollowupRetrieval(_production_rag_tool()),
        semantic_grader=StructuredSemanticClaimGrader(model),
    )


@lru_cache
def _production_rag_tool() -> ProductionRAGTool:
    settings=get_settings()
    return ProductionRAGTool(get_self_corrective_rag(),max_attempts=settings.self_corrective_rag_max_attempts,max_query_rewrites=settings.self_corrective_rag_max_query_rewrites,allow_scope_relaxation=settings.self_corrective_rag_allow_scope_relaxation,external_search_mode=settings.self_corrective_rag_external_search_mode)


@lru_cache
def get_incident_agent_bundle() -> IncidentAgentBundle:
    return IncidentAgentBundle(
        supervisor=get_supervisor_agent(), planning=get_planning_agent(), github=get_github_agent(),
        rag=get_rag_agent(), visual_evidence=get_visual_evidence_agent(),
        runtime_evidence=get_runtime_evidence_agent(), rca=get_rca_agent(), critic=get_critic_agent(),
        claim_verifier=get_hallucination_protector(),
        citation_service=get_citation_service(),
        approval_service=get_approval_service(),
        settings=get_settings(),
    )
