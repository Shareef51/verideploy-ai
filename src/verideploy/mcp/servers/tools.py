from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import MCPCallerContext, MCPPermission, MCPRisk, MCPToolDefinition, MCPToolEffect
from ..registry import MCPToolRegistry
from .contracts import GitHubBackend, IncidentBackend, KnowledgeBackend, MonitoringBackend


class TenantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str


class RepositoryGetInput(TenantInput):
    owner: str = Field(min_length=1, max_length=100)
    repo: str = Field(min_length=1, max_length=100)


class PullRequestGetInput(RepositoryGetInput):
    number: int = Field(ge=1)


class MonitoringQueryInput(TenantInput):
    query: str = Field(min_length=1, max_length=4000)
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    service: str = Field(min_length=1, max_length=120)
    environment: str = Field(min_length=1, max_length=80)


class KnowledgeSearchInput(TenantInput):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)


class IncidentGetInput(TenantInput):
    incident_id: str = Field(min_length=1, max_length=120)


class IncidentAddNoteInput(IncidentGetInput):
    note: str = Field(min_length=1, max_length=4000)


class GenericToolOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    data: dict[str, Any] = Field(default_factory=dict)


def register_tools(registry: MCPToolRegistry, *, github: GitHubBackend, monitoring: MonitoringBackend,
                           knowledge: KnowledgeBackend, incident: IncidentBackend, timeout_seconds: float = 15.0) -> None:
    async def repo_get(args: dict[str, Any], _: MCPCallerContext):
        return {"data": await github.repository_get(args["owner"], args["repo"])}

    async def pr_get(args: dict[str, Any], _: MCPCallerContext):
        return {"data": await github.pull_request_get(args["owner"], args["repo"], args["number"])}

    async def metrics(args: dict[str, Any], _: MCPCallerContext):
        return {"data": await monitoring.metrics_query(args["query"], args["start"], args["end"], args["service"], args["environment"])}

    async def search(args: dict[str, Any], _: MCPCallerContext):
        return {"data": await knowledge.search(args["query"], args["tenant_id"], args["top_k"])}

    async def incident_get(args: dict[str, Any], _: MCPCallerContext):
        return {"data": await incident.get(args["incident_id"], args["tenant_id"])}

    async def incident_note(args: dict[str, Any], _: MCPCallerContext):
        return {"data": await incident.add_note(args["incident_id"], args["tenant_id"], args["note"])}

    definitions = [
        MCPToolDefinition(name="github.repository.get", server_name="github", description="Read repository metadata.", permission=MCPPermission.GITHUB_READ, risk=MCPRisk.LOW, effect=MCPToolEffect.READ, input_model=RepositoryGetInput, output_model=GenericToolOutput, handler=repo_get, timeout_seconds=timeout_seconds),
        MCPToolDefinition(name="github.pull_request.get", server_name="github", description="Read pull request metadata.", permission=MCPPermission.GITHUB_READ, risk=MCPRisk.LOW, effect=MCPToolEffect.READ, input_model=PullRequestGetInput, output_model=GenericToolOutput, handler=pr_get, timeout_seconds=timeout_seconds),
        MCPToolDefinition(name="monitoring.metrics.query", server_name="monitoring", description="Read bounded runtime metrics.", permission=MCPPermission.MONITORING_READ, risk=MCPRisk.MEDIUM, effect=MCPToolEffect.READ, input_model=MonitoringQueryInput, output_model=GenericToolOutput, handler=metrics, timeout_seconds=timeout_seconds),
        MCPToolDefinition(name="knowledge.search", server_name="knowledge", description="Search tenant-scoped knowledge evidence.", permission=MCPPermission.KNOWLEDGE_READ, risk=MCPRisk.LOW, effect=MCPToolEffect.READ, input_model=KnowledgeSearchInput, output_model=GenericToolOutput, handler=search, timeout_seconds=timeout_seconds),
        MCPToolDefinition(name="incident.get", server_name="incident", description="Read an incident record.", permission=MCPPermission.INCIDENT_READ, risk=MCPRisk.LOW, effect=MCPToolEffect.READ, input_model=IncidentGetInput, output_model=GenericToolOutput, handler=incident_get, timeout_seconds=timeout_seconds),
        MCPToolDefinition(name="incident.add_note", server_name="incident", description="Add an audited human-approved incident note.", permission=MCPPermission.INCIDENT_WRITE, risk=MCPRisk.HIGH, effect=MCPToolEffect.WRITE, input_model=IncidentAddNoteInput, output_model=GenericToolOutput, handler=incident_note, timeout_seconds=timeout_seconds),
    ]
    for definition in definitions:
        registry.register(definition)
