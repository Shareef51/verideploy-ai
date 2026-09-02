from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Mapping, Protocol
from uuid import UUID

from sqlalchemy import text

from verideploy.approvals.schemas import ApprovalEvent, ApprovalRequest, ApprovalStatus
from verideploy.database.session import DatabaseManager


class ApprovalConflictError(RuntimeError):
    pass


class ApprovalRepository(Protocol):
    def create_or_get(self, request: ApprovalRequest, event: ApprovalEvent) -> ApprovalRequest: ...
    def get(self, *, tenant_id: UUID, approval_id: UUID) -> ApprovalRequest | None: ...
    def list_queue(self, *, tenant_id: UUID, reviewer_id: str | None = None) -> list[ApprovalRequest]: ...
    def transition(self, *, tenant_id: UUID, approval_id: UUID, expected_version: int, allowed_statuses: frozenset[ApprovalStatus], updated: ApprovalRequest, event: ApprovalEvent) -> ApprovalRequest: ...
    def list_events(self, *, tenant_id: UUID, approval_id: UUID) -> list[ApprovalEvent]: ...


class InMemoryApprovalRepository:
    def __init__(self) -> None:
        self._requests: dict[tuple[UUID, UUID], ApprovalRequest] = {}
        self._idempotency: dict[tuple[UUID, str], UUID] = {}
        self._events: dict[tuple[UUID, UUID], list[ApprovalEvent]] = {}
        self._lock = threading.RLock()

    def create_or_get(self, request: ApprovalRequest, event: ApprovalEvent) -> ApprovalRequest:
        with self._lock:
            idem = (request.tenant_id, request.idempotency_key)
            existing_id = self._idempotency.get(idem)
            if existing_id:
                return self._requests[(request.tenant_id, existing_id)].model_copy(deep=True)
            self._requests[(request.tenant_id, request.approval_id)] = request.model_copy(deep=True)
            self._idempotency[idem] = request.approval_id
            self._events[(request.tenant_id, request.approval_id)] = [event.model_copy(deep=True)]
            return request.model_copy(deep=True)

    def get(self, *, tenant_id: UUID, approval_id: UUID) -> ApprovalRequest | None:
        with self._lock:
            item = self._requests.get((tenant_id, approval_id))
            return None if item is None else item.model_copy(deep=True)

    def list_queue(self, *, tenant_id: UUID, reviewer_id: str | None = None) -> list[ApprovalRequest]:
        with self._lock:
            items = [r for (t, _), r in self._requests.items() if t == tenant_id and r.status in {ApprovalStatus.PENDING, ApprovalStatus.IN_REVIEW, ApprovalStatus.CHANGES_REQUESTED}]
            if reviewer_id:
                items = [r for r in items if r.delegated_to in {None, reviewer_id} or r.reviewer_id == reviewer_id]
            items.sort(key=lambda r: (-r.risk_score, r.expires_at, r.created_at, str(r.approval_id)))
            return [r.model_copy(deep=True) for r in items]

    def transition(self, *, tenant_id: UUID, approval_id: UUID, expected_version: int, allowed_statuses: frozenset[ApprovalStatus], updated: ApprovalRequest, event: ApprovalEvent) -> ApprovalRequest:
        with self._lock:
            key = (tenant_id, approval_id)
            current = self._requests.get(key)
            if current is None:
                raise KeyError("approval not found")
            if current.version != expected_version or current.status not in allowed_statuses:
                raise ApprovalConflictError("approval state changed concurrently")
            if event.sequence != len(self._events[key]) + 1:
                raise ApprovalConflictError("approval event sequence conflict")
            self._requests[key] = updated.model_copy(deep=True)
            self._events[key].append(event.model_copy(deep=True))
            return updated.model_copy(deep=True)

    def list_events(self, *, tenant_id: UUID, approval_id: UUID) -> list[ApprovalEvent]:
        with self._lock:
            return [e.model_copy(deep=True) for e in self._events.get((tenant_id, approval_id), ())]


class PostgresApprovalRepository:
    def __init__(self, database: DatabaseManager, *, statement_timeout_ms: int = 15_000) -> None:
        self.database = database
        self.statement_timeout_ms = statement_timeout_ms

    @staticmethod
    def _request(row: Mapping) -> ApprovalRequest:
        data = dict(row)
        data["action_payload"] = deepcopy(dict(data["action_payload"] or {}))
        data["evidence_summary"] = deepcopy(dict(data["evidence_summary"] or {}))
        data["policy"] = deepcopy(dict(data["policy"] or {}))
        return ApprovalRequest.model_validate(data)

    @staticmethod
    def _event(row: Mapping) -> ApprovalEvent:
        return ApprovalEvent.model_validate(dict(row))

    def create_or_get(self, request: ApprovalRequest, event: ApprovalEvent) -> ApprovalRequest:
        with self.database.tenant_session(request.tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            row = session.execute(text("""
                INSERT INTO approval_requests
                  (approval_id,tenant_id,run_id,investigation_id,action_type,action_payload,risk,risk_score,requested_by,
                   evidence_summary,policy,idempotency_key,status,reviewer_id,delegated_to,decision_comment,version,
                   expires_at,created_at,updated_at)
                VALUES
                  (:approval_id,:tenant_id,:run_id,:investigation_id,:action_type,CAST(:action_payload AS jsonb),:risk,:risk_score,:requested_by,
                   CAST(:evidence_summary AS jsonb),CAST(:policy AS jsonb),:idempotency_key,:status,:reviewer_id,:delegated_to,:decision_comment,:version,
                   :expires_at,:created_at,:updated_at)
                ON CONFLICT (tenant_id,idempotency_key) DO NOTHING
                RETURNING approval_id
            """), {
                "approval_id": request.approval_id, "tenant_id": request.tenant_id, "run_id": request.run_id,
                "investigation_id": request.investigation_id, "action_type": request.action_type,
                "action_payload": json.dumps(request.action_payload, sort_keys=True, separators=(",", ":")),
                "risk": request.risk.value, "risk_score": request.risk_score, "requested_by": request.requested_by,
                "evidence_summary": request.evidence_summary.model_dump_json(), "policy": request.policy.model_dump_json(),
                "idempotency_key": request.idempotency_key, "status": request.status.value, "reviewer_id": request.reviewer_id,
                "delegated_to": request.delegated_to, "decision_comment": request.decision_comment, "version": request.version,
                "expires_at": request.expires_at, "created_at": request.created_at, "updated_at": request.updated_at,
            }).mappings().first()
            if row is not None:
                self._insert_event(session, event)
            if row is None:
                approval_id = session.execute(text("SELECT approval_id FROM approval_requests WHERE tenant_id=:tenant_id AND idempotency_key=:key"), {"tenant_id": request.tenant_id, "key": request.idempotency_key}).scalar_one()
            else:
                approval_id = row["approval_id"]
            session.commit()
        result = self.get(tenant_id=request.tenant_id, approval_id=approval_id)
        if result is None:
            raise RuntimeError("approval was not persisted")
        return result

    def get(self, *, tenant_id: UUID, approval_id: UUID) -> ApprovalRequest | None:
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            row = session.execute(text("SELECT * FROM approval_requests WHERE tenant_id=:tenant_id AND approval_id=:approval_id"), {"tenant_id": tenant_id, "approval_id": approval_id}).mappings().first()
        return None if row is None else self._request(row)

    def list_queue(self, *, tenant_id: UUID, reviewer_id: str | None = None) -> list[ApprovalRequest]:
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            rows = session.execute(text("""
                SELECT * FROM approval_requests
                WHERE tenant_id=:tenant_id AND status IN ('pending','in_review','changes_requested')
                  AND (:reviewer_id IS NULL OR delegated_to IS NULL OR delegated_to=:reviewer_id OR reviewer_id=:reviewer_id)
                ORDER BY risk_score DESC, expires_at ASC, created_at ASC, approval_id ASC
            """), {"tenant_id": tenant_id, "reviewer_id": reviewer_id}).mappings().all()
        return [self._request(row) for row in rows]

    def transition(self, *, tenant_id: UUID, approval_id: UUID, expected_version: int, allowed_statuses: frozenset[ApprovalStatus], updated: ApprovalRequest, event: ApprovalEvent) -> ApprovalRequest:
        allowed = tuple(status.value for status in sorted(allowed_statuses, key=lambda s: s.value))
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            current = session.execute(text("""
                SELECT status,version FROM approval_requests
                WHERE tenant_id=:tenant_id AND approval_id=:approval_id
                FOR UPDATE
            """), {"tenant_id": tenant_id, "approval_id": approval_id}).mappings().first()
            if current is None:
                raise KeyError("approval not found")
            if int(current["version"]) != expected_version or current["status"] not in allowed:
                raise ApprovalConflictError("approval state changed concurrently")
            session.execute(text("""
                UPDATE approval_requests SET
                  status=:status,reviewer_id=:reviewer_id,delegated_to=:delegated_to,decision_comment=:decision_comment,
                  version=:version,updated_at=:updated_at
                WHERE tenant_id=:tenant_id AND approval_id=:approval_id AND version=:expected_version
            """), {
                "status": updated.status.value, "reviewer_id": updated.reviewer_id, "delegated_to": updated.delegated_to,
                "decision_comment": updated.decision_comment, "version": updated.version, "updated_at": updated.updated_at,
                "tenant_id": tenant_id, "approval_id": approval_id, "expected_version": expected_version,
            })
            self._insert_event(session, event)
            session.commit()
        result = self.get(tenant_id=tenant_id, approval_id=approval_id)
        assert result is not None
        return result

    def _insert_event(self, session, event: ApprovalEvent) -> None:
        session.execute(text("""
            INSERT INTO approval_events
              (event_id,approval_id,tenant_id,sequence,event_type,actor_id,actor_role,payload,previous_status,new_status,
               signed_payload_sha256,signature,occurred_at)
            VALUES
              (:event_id,:approval_id,:tenant_id,:sequence,:event_type,:actor_id,:actor_role,CAST(:payload AS jsonb),:previous_status,:new_status,
               :signed_payload_sha256,:signature,:occurred_at)
        """), {
            "event_id": event.event_id, "approval_id": event.approval_id, "tenant_id": event.tenant_id, "sequence": event.sequence,
            "event_type": event.event_type.value, "actor_id": event.actor_id, "actor_role": event.actor_role,
            "payload": json.dumps(event.payload, sort_keys=True, separators=(",", ":")),
            "previous_status": event.previous_status.value if event.previous_status else None,
            "new_status": event.new_status.value if event.new_status else None,
            "signed_payload_sha256": event.signed_payload_sha256, "signature": event.signature, "occurred_at": event.occurred_at,
        })

    def list_events(self, *, tenant_id: UUID, approval_id: UUID) -> list[ApprovalEvent]:
        with self.database.tenant_session(tenant_id, statement_timeout_ms=self.statement_timeout_ms) as session:
            rows = session.execute(text("SELECT * FROM approval_events WHERE tenant_id=:tenant_id AND approval_id=:approval_id ORDER BY sequence"), {"tenant_id": tenant_id, "approval_id": approval_id}).mappings().all()
        return [self._event(row) for row in rows]
