from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.graphs.runtime import GraphRunRecord, GraphRunStatus, GraphRuntimeEvent


class SqlAlchemyGraphRuntimeRepository:
    def __init__(self, database: DatabaseManager, *, statement_timeout_ms: int = 15_000) -> None:
        self.database = database
        self.statement_timeout_ms = statement_timeout_ms

    def create_run(self, *, tenant_id: UUID, run_id: UUID, thread_id: str, graph_name: str, graph_version: str, correlation_id: str) -> GraphRunRecord:
        now = datetime.now(timezone.utc)
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            session.execute(text("""
                INSERT INTO graph_runs
                    (run_id, tenant_id, thread_id, graph_name, graph_version, correlation_id, status, last_sequence, created_at, updated_at)
                VALUES (:run_id, :tenant_id, :thread_id, :graph_name, :graph_version, :correlation_id, :status, 0, :now, :now)
                ON CONFLICT (tenant_id, run_id) DO NOTHING
            """), {"run_id": run_id, "tenant_id": tenant_id, "thread_id": thread_id, "graph_name": graph_name, "graph_version": graph_version, "correlation_id": correlation_id, "status": GraphRunStatus.PENDING.value, "now": now})
            session.commit()
        record = self.get_run(tenant_id=tenant_id, run_id=run_id)
        if record is None:
            raise RuntimeError("graph run was not persisted")
        return record

    def get_run(self, *, tenant_id: UUID, run_id: UUID) -> GraphRunRecord | None:
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            row = session.execute(text("""
                SELECT run_id, tenant_id, thread_id, graph_name, graph_version, correlation_id,
                       status, last_sequence, error_code, created_at, updated_at
                FROM graph_runs WHERE tenant_id=:tenant_id AND run_id=:run_id
            """), {"tenant_id": tenant_id, "run_id": run_id}).mappings().first()
        return None if row is None else GraphRunRecord.model_validate(dict(row))

    def set_status(self, *, tenant_id: UUID, run_id: UUID, status: GraphRunStatus, error_code: str | None = None) -> GraphRunRecord:
        now = datetime.now(timezone.utc)
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            result = session.execute(text("""
                UPDATE graph_runs SET status=:status, error_code=:error_code, updated_at=:now
                WHERE tenant_id=:tenant_id AND run_id=:run_id
            """), {"status": status.value, "error_code": error_code, "now": now, "tenant_id": tenant_id, "run_id": run_id})
            if result.rowcount != 1:
                raise KeyError("graph run not found")
            session.commit()
        record = self.get_run(tenant_id=tenant_id, run_id=run_id)
        assert record is not None
        return record

    def append_event(self, *, tenant_id: UUID, run_id: UUID, thread_id: str, graph_name: str, graph_version: str, event_type: str, node_name: str | None = None, payload: dict | None = None) -> GraphRuntimeEvent:
        now = datetime.now(timezone.utc)
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            row = session.execute(text("""
                UPDATE graph_runs SET last_sequence=last_sequence+1, updated_at=:now
                WHERE tenant_id=:tenant_id AND run_id=:run_id
                RETURNING last_sequence
            """), {"now": now, "tenant_id": tenant_id, "run_id": run_id}).mappings().first()
            if row is None:
                raise KeyError("graph run not found")
            event = GraphRuntimeEvent(
                tenant_id=tenant_id, run_id=run_id, thread_id=thread_id,
                sequence_number=int(row["last_sequence"]), event_type=event_type,
                graph_name=graph_name, graph_version=graph_version, node_name=node_name,
                payload=payload or {}, occurred_at=now,
            )
            session.execute(text("""
                INSERT INTO graph_runtime_events
                    (event_id, tenant_id, run_id, sequence_number, event_type, node_name, payload, occurred_at)
                VALUES (:event_id, :tenant_id, :run_id, :sequence_number, :event_type, :node_name, CAST(:payload AS jsonb), :occurred_at)
            """), {"event_id": event.event_id, "tenant_id": tenant_id, "run_id": run_id, "sequence_number": event.sequence_number, "event_type": event_type, "node_name": node_name, "payload": json.dumps(event.payload, separators=(",", ":"), sort_keys=True), "occurred_at": now})
            session.commit()
        return event

    def list_events(self, *, tenant_id: UUID, run_id: UUID, after_sequence: int = 0) -> list[GraphRuntimeEvent]:
        run = self.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            return []
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            rows = session.execute(text("""
                SELECT event_id, tenant_id, run_id, sequence_number, event_type, node_name, payload, occurred_at
                FROM graph_runtime_events
                WHERE tenant_id=:tenant_id AND run_id=:run_id AND sequence_number>:after_sequence
                ORDER BY sequence_number
            """), {"tenant_id": tenant_id, "run_id": run_id, "after_sequence": after_sequence}).mappings().all()
        return [GraphRuntimeEvent(thread_id=run.thread_id, graph_name=run.graph_name, graph_version=run.graph_version, **dict(row)) for row in rows]
