from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse
from verideploy.config import Settings
from .adapters import GitHubIntegration, JiraIntegration, RangeIntegration, SyntheticIntegrationBundle
from .contracts import IntegrationType
from .http import HTTPIntegrationPolicy

def _hosts(csv: str) -> set[str]:
    return {item.strip().lower() for item in csv.split(",") if item.strip()}

def _host(url: str | None) -> str | None:
    return urlparse(url).hostname if url else None

@dataclass(frozen=True)
class EngineeringIntegrations:
    github: GitHubIntegration
    jira: JiraIntegration
    prometheus: RangeIntegration
    grafana: RangeIntegration
    traces: RangeIntegration
    logs: RangeIntegration
    synthetic: SyntheticIntegrationBundle

def create_engineering_integrations(settings: Settings, *, transports: dict[str, object] | None=None) -> EngineeringIntegrations:
    transports=transports or {}
    policy=HTTPIntegrationPolicy(max_attempts=settings.integration_max_attempts,max_requests=settings.integration_max_requests_per_run,timeout_seconds=settings.integration_http_timeout_seconds,backoff_base_seconds=settings.integration_backoff_base_seconds,max_retry_delay_seconds=settings.integration_max_retry_delay_seconds)
    allowed=_hosts(settings.integration_allowed_hosts)
    # Configured endpoint hosts must be deliberately present in the shared allowlist.
    def allowed_for(url: str | None) -> set[str]:
        host=_host(url)
        return allowed if host else allowed
    return EngineeringIntegrations(
        github=GitHubIntegration(base_url=settings.github_api_base_url if settings.github_api_token else None, token=settings.github_api_token.get_secret_value() if settings.github_api_token else None, allowed_hosts=allowed_for(settings.github_api_base_url),transport=transports.get("github"),policy=policy),
        jira=JiraIntegration(base_url=settings.jira_base_url if settings.jira_api_token else None, token=settings.jira_api_token.get_secret_value() if settings.jira_api_token else None, email=settings.jira_email, auth_mode=settings.jira_auth_mode, allowed_hosts=allowed_for(settings.jira_base_url),transport=transports.get("jira"),policy=policy),
        prometheus=RangeIntegration(IntegrationType.PROMETHEUS,base_url=settings.prometheus_base_url,path="/api/v1/query_range",token=settings.runtime_observability_token.get_secret_value() if settings.runtime_observability_token else None,allowed_hosts=allowed_for(settings.prometheus_base_url),transport=transports.get("prometheus"),policy=policy),
        grafana=RangeIntegration(IntegrationType.GRAFANA,base_url=settings.grafana_base_url,path="/api/annotations",token=settings.runtime_observability_token.get_secret_value() if settings.runtime_observability_token else None,allowed_hosts=allowed_for(settings.grafana_base_url),transport=transports.get("grafana"),policy=policy),
        traces=RangeIntegration(IntegrationType.TRACE,base_url=settings.tempo_base_url,path="/api/search",token=settings.runtime_observability_token.get_secret_value() if settings.runtime_observability_token else None,allowed_hosts=allowed_for(settings.tempo_base_url),transport=transports.get("trace"),policy=policy),
        logs=RangeIntegration(IntegrationType.LOG,base_url=settings.loki_base_url,path="/loki/api/v1/query_range",token=settings.runtime_observability_token.get_secret_value() if settings.runtime_observability_token else None,allowed_hosts=allowed_for(settings.loki_base_url),transport=transports.get("log"),policy=policy),
        synthetic=SyntheticIntegrationBundle(),
    )
