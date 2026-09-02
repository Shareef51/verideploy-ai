from __future__ import annotations

from verideploy.config import get_settings
from verideploy.investigations.repository import SqlAlchemyInvestigationRepository

from .gateway import SecureMCPGateway
from .registry import MCPToolRegistry
from .repository import SqlAlchemyMCPAuditRepository
from .servers.adapters import HybridKnowledgeBackend, InvestigationIncidentBackend, RuntimeMonitoringBackend
from verideploy.integrations.factory import create_engineering_integrations
from .servers.tools import register_tools


def create_mcp_gateway(*, retriever, runtime_prometheus) -> SecureMCPGateway:
    settings = get_settings()
    registry = MCPToolRegistry()
    # Real Engineering Data Integrations production GitHub adapter owns host allowlisting, bounded retries, quotas, and secret isolation.
    github = create_engineering_integrations(settings).github
    knowledge = HybridKnowledgeBackend(retriever, model_name=settings.openai_embedding_model,
                                       dimensions=settings.openai_embedding_dimensions,
                                       candidate_k=settings.retrieval_candidate_k)
    monitoring = RuntimeMonitoringBackend(runtime_prometheus)
    incidents = InvestigationIncidentBackend(SqlAlchemyInvestigationRepository(settings.database_url, create_schema=settings.app_env == "test"))
    register_tools(registry, github=github, monitoring=monitoring, knowledge=knowledge, incident=incidents,
                           timeout_seconds=settings.mcp_tool_timeout_seconds)
    audit = SqlAlchemyMCPAuditRepository(settings.database_url, create_schema=settings.app_env == "test")
    return SecureMCPGateway(
        registry=registry, audit=audit, external_writes_enabled=settings.mcp_external_writes_enabled,
        breaker_threshold=settings.mcp_circuit_breaker_threshold,
        breaker_reset_seconds=settings.mcp_circuit_breaker_reset_seconds,
    )
