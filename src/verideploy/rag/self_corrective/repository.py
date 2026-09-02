from __future__ import annotations

import copy
import json
from typing import Protocol
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from .schemas import SelfCorrectiveRAGResult


class SelfCorrectiveRunRepository(Protocol):
    def save(self, result: SelfCorrectiveRAGResult) -> None: ...
    def get(self, *, tenant_id: UUID, run_id: UUID) -> SelfCorrectiveRAGResult | None: ...


class InMemorySelfCorrectiveRunRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[UUID, UUID], SelfCorrectiveRAGResult] = {}

    def save(self, result: SelfCorrectiveRAGResult) -> None:
        self._items[(result.tenant_id, result.run_id)] = copy.deepcopy(result)

    def get(self, *, tenant_id: UUID, run_id: UUID) -> SelfCorrectiveRAGResult | None:
        item = self._items.get((tenant_id, run_id))
        return copy.deepcopy(item) if item else None


class PostgresSelfCorrectiveRunRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def save(self, result: SelfCorrectiveRAGResult) -> None:
        payload = result.model_dump(mode="json")
        with self.db.transaction(result.tenant_id) as session:
            session.execute(text("""
                INSERT INTO self_corrective_rag_runs
                  (run_id, tenant_id, controller_version, stop_reason, answerable, qualified, result_json)
                VALUES (:run_id, :tenant_id, :version, :stop_reason, :answerable, :qualified, CAST(:result_json AS jsonb))
            """), {
                "run_id": str(result.run_id), "tenant_id": str(result.tenant_id), "version": result.controller_version,
                "stop_reason": result.stop_reason.value, "answerable": result.answerable, "qualified": result.qualified,
                "result_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            })
            for attempt in result.attempts:
                session.execute(text("""
                    INSERT INTO self_corrective_rag_attempts
                      (run_id, tenant_id, attempt_number, action, query_text, requested_scope_relaxed,
                       retrieval_run_id, evidence_grade, evidence_score, scope_fingerprint, attempt_json)
                    VALUES (:run_id, :tenant_id, :attempt, :action, :query, :relaxed,
                            :retrieval_run_id, :grade, :score, :fingerprint, CAST(:attempt_json AS jsonb))
                """), {
                    "run_id": str(result.run_id), "tenant_id": str(result.tenant_id), "attempt": attempt.attempt,
                    "action": attempt.action, "query": attempt.query, "relaxed": attempt.requested_scope_relaxed,
                    "retrieval_run_id": str(attempt.retrieval_run_id), "grade": attempt.grade.grade.value,
                    "score": attempt.grade.score, "fingerprint": attempt.effective_scope_fingerprint,
                    "attempt_json": json.dumps(attempt.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                })

    def get(self, *, tenant_id: UUID, run_id: UUID) -> SelfCorrectiveRAGResult | None:
        with self.db.transaction(tenant_id) as session:
            row = session.execute(text("SELECT result_json FROM self_corrective_rag_runs WHERE tenant_id=:tenant_id AND run_id=:run_id"), {"tenant_id": str(tenant_id), "run_id": str(run_id)}).scalar_one_or_none()
        return SelfCorrectiveRAGResult.model_validate(row) if row else None
