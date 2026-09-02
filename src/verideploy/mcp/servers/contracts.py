from __future__ import annotations

from typing import Any, Protocol


class GitHubBackend(Protocol):
    async def repository_get(self, owner: str, repo: str) -> dict[str, Any]: ...
    async def pull_request_get(self, owner: str, repo: str, number: int) -> dict[str, Any]: ...


class MonitoringBackend(Protocol):
    async def metrics_query(self, query: str, start: str, end: str, service: str, environment: str) -> dict[str, Any]: ...


class KnowledgeBackend(Protocol):
    async def search(self, query: str, tenant_id: str, top_k: int) -> dict[str, Any]: ...


class IncidentBackend(Protocol):
    async def get(self, incident_id: str, tenant_id: str) -> dict[str, Any]: ...
    async def add_note(self, incident_id: str, tenant_id: str, note: str) -> dict[str, Any]: ...
