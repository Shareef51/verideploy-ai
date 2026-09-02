from __future__ import annotations

from functools import lru_cache

from services.ai.retrieval import get_hybrid_retriever
from verideploy.agents.runtime_tools import LiveRuntimeEndpoints, LiveRuntimeTool, RuntimeSource, SyntheticRuntimeTool
from verideploy.config import get_settings
from verideploy.mcp.factory import create_mcp_gateway
from verideploy.mcp.gateway import SecureMCPGateway


@lru_cache
def get_mcp_gateway() -> SecureMCPGateway:
    settings = get_settings()
    if settings.runtime_evidence_adapter == "live":
        endpoints = LiveRuntimeEndpoints(
            prometheus_url=settings.prometheus_base_url, grafana_url=settings.grafana_base_url,
            tempo_url=settings.tempo_base_url, loki_url=settings.loki_base_url,
            bearer_token=settings.runtime_observability_token.get_secret_value() if settings.runtime_observability_token else None,
        )
        prometheus = LiveRuntimeTool(RuntimeSource.PROMETHEUS, endpoints, timeout_seconds=settings.runtime_http_timeout_seconds)
    else:
        prometheus = SyntheticRuntimeTool(RuntimeSource.PROMETHEUS)
    return create_mcp_gateway(retriever=get_hybrid_retriever(), runtime_prometheus=prometheus)
