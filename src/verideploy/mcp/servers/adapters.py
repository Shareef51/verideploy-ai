from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID


from verideploy.agents.runtime_tools import RuntimeSource, RuntimeToolPort, RuntimeToolQuery
from verideploy.investigations.repository import InvestigationRepository
from verideploy.rag.retrieval.schemas import RetrievalChannel, RetrievalQuery
from verideploy.rag.retrieval.service import HybridRetriever


class HybridKnowledgeBackend:
    def __init__(self, retriever: HybridRetriever, *, model_name: str, dimensions: int, candidate_k: int = 30) -> None:
        self.retriever = retriever
        self.model_name = model_name
        self.dimensions = dimensions
        self.candidate_k = candidate_k

    async def search(self, query: str, tenant_id: str, top_k: int) -> dict[str, Any]:
        result = await self.retriever.retrieve_mode(
            RetrievalQuery(tenant_id=UUID(tenant_id), query_text=query, top_k=top_k, candidate_k=max(top_k, self.candidate_k)),
            mode=RetrievalChannel.HYBRID, model_name=self.model_name, dimensions=self.dimensions,
        )
        return {"trace_id": str(result.trace.trace_id), "hits": [hit.model_dump(mode="json") for hit in result.hits]}


class RuntimeMonitoringBackend:
    """MCP monitoring adapter backed by Runtime Evidence Agent's authorized runtime source port."""

    def __init__(self, prometheus: RuntimeToolPort) -> None:
        self.prometheus = prometheus

    async def metrics_query(self, query: str, start: str, end: str, service: str, environment: str) -> dict[str, Any]:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        span = end_dt - start_dt
        request = RuntimeToolQuery(
            source=RuntimeSource.PROMETHEUS, service=service, environment=environment, query=query,
            start=start_dt, end=end_dt, baseline_start=start_dt - span, baseline_end=start_dt, limit=200,
        )
        result = await self.prometheus.query(request)
        return result.model_dump(mode="json")


class InvestigationIncidentBackend:
    def __init__(self, repository: InvestigationRepository) -> None:
        self.repository = repository

    async def get(self, incident_id: str, tenant_id: str) -> dict[str, Any]:
        try:
            investigation_id = UUID(incident_id)
        except ValueError as exc:
            raise KeyError("incident_id must reference a VeriDeploy investigation UUID") from exc
        record = self.repository.get(UUID(tenant_id), investigation_id)
        if record is None:
            raise KeyError(incident_id)
        return record.model_dump(mode="json")

    async def add_note(self, incident_id: str, tenant_id: str, note: str) -> dict[str, Any]:
        investigation_id = UUID(incident_id)
        record = self.repository.get(UUID(tenant_id), investigation_id)
        if record is None:
            raise KeyError(incident_id)
        event = self.repository.append_event(record.event(
            event_type="investigation.human_note_added", producer="mcp-incident-server",
            payload={"note": note},
        )) if hasattr(record, "event") else None
        if event is None:
            # Existing Incident Realtime Sequence record has no event factory; write through repository event contract explicitly.
            from datetime import UTC, datetime
            from uuid import uuid4
            from verideploy.investigations.schemas import InvestigationEvent
            event = self.repository.append_event(InvestigationEvent(
                event_id=uuid4(), event_type="investigation.human_note_added", schema_version="1.0",
                tenant_id=UUID(tenant_id), correlation_id=record.correlation_id,
                investigation_id=investigation_id, sequence_number=record.last_sequence_number + 1,
                occurred_at=datetime.now(UTC), producer="mcp-incident-server", trace_context={}, payload={"note": note},
            ))
        return {"event_id": str(event.event_id), "sequence_number": event.sequence_number}
