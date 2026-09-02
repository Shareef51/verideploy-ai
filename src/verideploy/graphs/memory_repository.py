from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from verideploy.graphs.runtime import GraphRunRecord, GraphRunStatus, GraphRuntimeEvent


class InMemoryGraphRuntimeRepository:
    def __init__(self) -> None:
        self.runs: dict[tuple[UUID, UUID], GraphRunRecord] = {}
        self.events: dict[tuple[UUID, UUID], list[GraphRuntimeEvent]] = {}

    def create_run(self, *, tenant_id: UUID, run_id: UUID, thread_id: str, graph_name: str, graph_version: str, correlation_id: str) -> GraphRunRecord:
        now = datetime.now(timezone.utc)
        key = (tenant_id, run_id)
        record = self.runs.get(key)
        if record is None:
            record = GraphRunRecord(run_id=run_id, tenant_id=tenant_id, thread_id=thread_id, graph_name=graph_name, graph_version=graph_version, correlation_id=correlation_id, status=GraphRunStatus.PENDING, created_at=now, updated_at=now)
            self.runs[key] = record
            self.events[key] = []
        return record

    def get_run(self, *, tenant_id: UUID, run_id: UUID) -> GraphRunRecord | None:
        return self.runs.get((tenant_id, run_id))

    def set_status(self, *, tenant_id: UUID, run_id: UUID, status: GraphRunStatus, error_code: str | None = None) -> GraphRunRecord:
        key = (tenant_id, run_id)
        record = self.runs[key].model_copy(update={"status": status, "error_code": error_code, "updated_at": datetime.now(timezone.utc)})
        self.runs[key] = record
        return record

    def append_event(self, *, tenant_id: UUID, run_id: UUID, thread_id: str, graph_name: str, graph_version: str, event_type: str, node_name: str | None = None, payload: dict | None = None) -> GraphRuntimeEvent:
        key = (tenant_id, run_id)
        seq = len(self.events[key]) + 1
        event = GraphRuntimeEvent(tenant_id=tenant_id, run_id=run_id, thread_id=thread_id, sequence_number=seq, event_type=event_type, graph_name=graph_name, graph_version=graph_version, node_name=node_name, payload=payload or {})
        self.events[key].append(event)
        self.runs[key] = self.runs[key].model_copy(update={"last_sequence": seq, "updated_at": event.occurred_at})
        return event

    def list_events(self, *, tenant_id: UUID, run_id: UUID, after_sequence: int = 0) -> list[GraphRuntimeEvent]:
        return [event for event in self.events.get((tenant_id, run_id), []) if event.sequence_number > after_sequence]
