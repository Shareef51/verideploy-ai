from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.rag.orchestration.schemas import RetrievalPipelineTrace


class RetrievalPipelineTraceRepository(ABC):
    @abstractmethod
    def save(self, trace: RetrievalPipelineTrace) -> None: ...

    @abstractmethod
    def get(self, *, tenant_id: UUID, run_id: UUID) -> RetrievalPipelineTrace | None: ...


class MemoryRetrievalPipelineTraceRepository(RetrievalPipelineTraceRepository):
    def __init__(self) -> None:
        self._items: dict[tuple[UUID, UUID], dict] = {}

    def save(self, trace: RetrievalPipelineTrace) -> None:
        self._items[(trace.tenant_id, trace.run_id)] = deepcopy(trace.model_dump(mode="json"))

    def get(self, *, tenant_id: UUID, run_id: UUID) -> RetrievalPipelineTrace | None:
        value = self._items.get((tenant_id, run_id))
        return RetrievalPipelineTrace.model_validate(deepcopy(value)) if value is not None else None


class PostgresRetrievalPipelineTraceRepository(RetrievalPipelineTraceRepository):
    def __init__(self, db: DatabaseManager) -> None:
        if db.engine.dialect.name != "postgresql":
            raise ValueError("PostgresRetrievalPipelineTraceRepository requires PostgreSQL")
        self.db = db

    def save(self, trace: RetrievalPipelineTrace) -> None:
        payload = trace.model_dump(mode="json")
        sql = text("""
            INSERT INTO retrieval_pipeline_runs
                (run_id, tenant_id, pipeline_version, input_sha256, query_text, trace_json, context_sha256)
            VALUES
                (:run_id, :tenant_id, :pipeline_version, :input_sha256, :query_text, CAST(:trace_json AS jsonb), :context_sha256)
            ON CONFLICT (run_id) DO NOTHING
        """)
        decision_sql = text("""
            INSERT INTO retrieval_ranking_decisions
                (decision_id, run_id, tenant_id, stage, ordinal, chunk_id, document_id, source_key,
                 input_score, output_score, action, reason_code, components, source_version)
            VALUES
                (:decision_id, :run_id, :tenant_id, :stage, :ordinal, :chunk_id, :document_id, :source_key,
                 :input_score, :output_score, :action, :reason_code, CAST(:components AS jsonb), :source_version)
            ON CONFLICT (run_id, stage, ordinal) DO NOTHING
        """)
        import json
        from uuid import uuid5, NAMESPACE_URL
        with self.db.tenant_session(trace.tenant_id) as session:
            session.execute(sql, {
                "run_id": str(trace.run_id), "tenant_id": str(trace.tenant_id),
                "pipeline_version": trace.pipeline_version, "input_sha256": trace.input_sha256,
                "query_text": trace.analysis.normalized_query,
                "trace_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
                "context_sha256": trace.context_sha256,
            })
            for item in trace.decisions:
                decision_id = uuid5(NAMESPACE_URL, f":{trace.run_id}:{item.stage.value}:{item.ordinal}")
                session.execute(decision_sql, {
                    "decision_id": str(decision_id), "run_id": str(trace.run_id), "tenant_id": str(trace.tenant_id),
                    "stage": item.stage.value, "ordinal": item.ordinal,
                    "chunk_id": str(item.chunk_id) if item.chunk_id else None,
                    "document_id": str(item.document_id) if item.document_id else None,
                    "source_key": item.source_key, "input_score": item.input_score, "output_score": item.output_score,
                    "action": item.action.value, "reason_code": item.reason_code,
                    "components": json.dumps(item.components, sort_keys=True, separators=(",", ":")),
                    "source_version": item.source_version,
                })
            session.commit()

    def get(self, *, tenant_id: UUID, run_id: UUID) -> RetrievalPipelineTrace | None:
        sql = text("SELECT trace_json FROM retrieval_pipeline_runs WHERE tenant_id=:tenant_id AND run_id=:run_id")
        with self.db.tenant_session(tenant_id) as session:
            value = session.scalar(sql, {"tenant_id": str(tenant_id), "run_id": str(run_id)})
        return RetrievalPipelineTrace.model_validate(value) if value is not None else None
