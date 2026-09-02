from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

_SECRET_KEY = re.compile(r"(?i)(authorization|cookie|set-cookie|api[_-]?key|secret|password|token|private[_-]?key|session)")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")

class ActorType(StrEnum):
    USER = "user"
    SERVICE = "service"
    AGENT = "agent"
    SYSTEM = "system"

class AuditResult(StrEnum):
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    FAILED = "failed"
    CANCELLED = "cancelled"

class RetentionClass(StrEnum):
    STANDARD = "standard"
    SECURITY = "security"
    LEGAL = "legal"

@dataclass(frozen=True)
class AuditPolicy:
    version: str = "1.0.0"
    standard_days: int = 365
    security_days: int = 2555
    export_roles: frozenset[str] = frozenset({"security_admin", "auditor"})
    search_roles: frozenset[str] = frozenset({"viewer", "developer", "reviewer", "security_admin", "auditor"})

@dataclass(frozen=True)
class AuditActor:
    actor_type: ActorType
    actor_id: str
    roles: tuple[str, ...] = ()
    service_id: str | None = None

@dataclass(frozen=True)
class AuditResource:
    resource_type: str
    resource_id: str
    tenant_id: str

@dataclass(frozen=True)
class AuditReviewSignature:
    reviewer_id: str
    algorithm: str
    key_id: str
    signature: str
    signed_at: datetime

@dataclass(frozen=True)
class AuditEvent:
    audit_id: str
    tenant_id: str
    sequence: int
    occurred_at: datetime
    actor: AuditActor
    resource: AuditResource
    action: str
    result: AuditResult
    correlation_id: str
    trace_id: str | None
    span_id: str | None
    source: str
    reason_code: str | None
    payload: Mapping[str, Any]
    retention_class: RetentionClass
    retain_until: datetime
    legal_hold: bool
    previous_hash: str
    event_hash: str
    review_signature: AuditReviewSignature | None = None

@dataclass(frozen=True)
class AuditSearchQuery:
    tenant_id: str
    requester_id: str
    requester_roles: tuple[str, ...]
    actor_id: str | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    result: AuditResult | None = None
    correlation_id: str | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None
    limit: int = 200

@dataclass(frozen=True)
class AuditExport:
    format: str
    content: str
    sha256: str
    event_count: int

class AuditAuthorizationError(PermissionError):
    pass

class AuditIntegrityError(RuntimeError):
    pass

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")

def redact_audit_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = redact_audit_payload(item)
        return out
    if isinstance(value, list):
        return [redact_audit_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_audit_payload(item) for item in value]
    if isinstance(value, str):
        return _BEARER.sub("Bearer [REDACTED]", value)
    return value

def compute_event_hash(*, previous_hash: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256(previous_hash.encode("ascii") + b"\n" + _canonical(body)).hexdigest()

def _event_body(event: AuditEvent, *, include_hashes: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {
        "audit_id": event.audit_id,
        "tenant_id": event.tenant_id,
        "sequence": event.sequence,
        "occurred_at": event.occurred_at.isoformat(),
        "actor": {"actor_type": event.actor.actor_type.value, "actor_id": event.actor.actor_id, "roles": list(event.actor.roles), "service_id": event.actor.service_id},
        "resource": {"resource_type": event.resource.resource_type, "resource_id": event.resource.resource_id, "tenant_id": event.resource.tenant_id},
        "action": event.action,
        "result": event.result.value,
        "correlation_id": event.correlation_id,
        "trace_id": event.trace_id,
        "span_id": event.span_id,
        "source": event.source,
        "reason_code": event.reason_code,
        "payload": event.payload,
        "retention_class": event.retention_class.value,
        "retain_until": event.retain_until.isoformat(),
        "legal_hold": event.legal_hold,
    }
    if include_hashes:
        body.update(previous_hash=event.previous_hash, event_hash=event.event_hash)
    return body

class AuditTrail:
    """Append-only, tenant-isolated audit trail with hash-chain tamper evidence.

    This implementation is deterministic and storage-neutral; production persistence is
    provided by the audit-compliance PostgreSQL migration. It is also used by CI/red-team tests.
    """

    def __init__(self, policy: AuditPolicy | None = None):
        self.policy = policy or AuditPolicy()
        self._events: list[AuditEvent] = []
        self._last_hash_by_tenant: dict[str, str] = {}
        self._sequence_by_tenant: dict[str, int] = {}

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        *,
        tenant_id: str,
        actor: AuditActor,
        resource_type: str,
        resource_id: str,
        action: str,
        result: AuditResult,
        correlation_id: str,
        source: str,
        payload: Mapping[str, Any] | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        reason_code: str | None = None,
        retention_class: RetentionClass = RetentionClass.STANDARD,
        legal_hold: bool = False,
        occurred_at: datetime | None = None,
    ) -> AuditEvent:
        if not tenant_id or not actor.actor_id or not action or not resource_type or not resource_id or not correlation_id:
            raise ValueError("audit actor/resource/action/correlation fields are required")
        when = occurred_at or utcnow()
        if when.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        seq = self._sequence_by_tenant.get(tenant_id, 0) + 1
        prev = self._last_hash_by_tenant.get(tenant_id, "0" * 64)
        days = self.policy.security_days if retention_class in {RetentionClass.SECURITY, RetentionClass.LEGAL} else self.policy.standard_days
        sanitized = redact_audit_payload(dict(payload or {}))
        event = AuditEvent(
            audit_id=str(uuid4()), tenant_id=tenant_id, sequence=seq, occurred_at=when,
            actor=actor, resource=AuditResource(resource_type, resource_id, tenant_id),
            action=action, result=result, correlation_id=correlation_id, trace_id=trace_id,
            span_id=span_id, source=source, reason_code=reason_code, payload=sanitized,
            retention_class=retention_class, retain_until=when + timedelta(days=days), legal_hold=legal_hold,
            previous_hash=prev, event_hash="",
        )
        body = _event_body(event)
        event = AuditEvent(**{**event.__dict__, "event_hash": compute_event_hash(previous_hash=prev, body=body)})
        self._events.append(event)
        self._last_hash_by_tenant[tenant_id] = event.event_hash
        self._sequence_by_tenant[tenant_id] = seq
        return event

    def sign_review(self, audit_id: str, *, reviewer_id: str, key_id: str, signing_key: bytes, signed_at: datetime | None = None) -> AuditEvent:
        event = self._find(audit_id)
        when = signed_at or utcnow()
        material = f"{event.audit_id}:{event.event_hash}:{reviewer_id}:{when.isoformat()}".encode()
        signature = hmac.new(signing_key, material, hashlib.sha256).hexdigest()
        signed = AuditReviewSignature(reviewer_id, "HMAC-SHA256", key_id, signature, when)
        replacement = AuditEvent(**{**event.__dict__, "review_signature": signed})
        self._replace(audit_id, replacement)
        return replacement

    @staticmethod
    def verify_review_signature(event: AuditEvent, signing_key: bytes) -> bool:
        sig = event.review_signature
        if sig is None or sig.algorithm != "HMAC-SHA256":
            return False
        material = f"{event.audit_id}:{event.event_hash}:{sig.reviewer_id}:{sig.signed_at.isoformat()}".encode()
        expected = hmac.new(signing_key, material, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig.signature)

    def verify_chain(self, tenant_id: str) -> bool:
        previous = "0" * 64
        expected_sequence = 1
        for event in [e for e in self._events if e.tenant_id == tenant_id]:
            if event.sequence != expected_sequence or event.previous_hash != previous:
                raise AuditIntegrityError(f"audit chain sequence/hash break at {event.audit_id}")
            calculated = compute_event_hash(previous_hash=previous, body=_event_body(event))
            if not hmac.compare_digest(calculated, event.event_hash):
                raise AuditIntegrityError(f"audit event hash mismatch at {event.audit_id}")
            previous = event.event_hash
            expected_sequence += 1
        return True

    def search(self, query: AuditSearchQuery) -> list[AuditEvent]:
        roles = set(query.requester_roles)
        if not roles.intersection(self.policy.search_roles):
            raise AuditAuthorizationError("audit search is not authorized")
        limit = max(1, min(query.limit, 1000))
        rows = [e for e in self._events if e.tenant_id == query.tenant_id]
        if query.actor_id: rows = [e for e in rows if e.actor.actor_id == query.actor_id]
        if query.action: rows = [e for e in rows if e.action == query.action]
        if query.resource_type: rows = [e for e in rows if e.resource.resource_type == query.resource_type]
        if query.resource_id: rows = [e for e in rows if e.resource.resource_id == query.resource_id]
        if query.result: rows = [e for e in rows if e.result == query.result]
        if query.correlation_id: rows = [e for e in rows if e.correlation_id == query.correlation_id]
        if query.from_time: rows = [e for e in rows if e.occurred_at >= query.from_time]
        if query.to_time: rows = [e for e in rows if e.occurred_at <= query.to_time]
        return sorted(rows, key=lambda e: (e.occurred_at, e.sequence), reverse=True)[:limit]

    def export(self, query: AuditSearchQuery, *, format: str = "jsonl") -> AuditExport:
        if not set(query.requester_roles).intersection(self.policy.export_roles):
            raise AuditAuthorizationError("audit export requires auditor or security_admin")
        events = self.search(query)
        if format == "jsonl":
            content = "\n".join(json.dumps(_event_body(e, include_hashes=True), sort_keys=True, default=str) for e in events)
        elif format == "csv":
            buf = io.StringIO(); writer = csv.DictWriter(buf, fieldnames=["audit_id","occurred_at","actor_type","actor_id","action","resource_type","resource_id","result","correlation_id","trace_id","event_hash"]); writer.writeheader()
            for e in events:
                writer.writerow({"audit_id":e.audit_id,"occurred_at":e.occurred_at.isoformat(),"actor_type":e.actor.actor_type.value,"actor_id":e.actor.actor_id,"action":e.action,"resource_type":e.resource.resource_type,"resource_id":e.resource.resource_id,"result":e.result.value,"correlation_id":e.correlation_id,"trace_id":e.trace_id,"event_hash":e.event_hash})
            content = buf.getvalue()
        else:
            raise ValueError("audit export format must be jsonl or csv")
        return AuditExport(format, content, hashlib.sha256(content.encode()).hexdigest(), len(events))

    def eligible_for_purge(self, *, now: datetime | None = None) -> tuple[AuditEvent, ...]:
        current = now or utcnow()
        return tuple(e for e in self._events if not e.legal_hold and e.retain_until <= current)

    def _find(self, audit_id: str) -> AuditEvent:
        for event in self._events:
            if event.audit_id == audit_id: return event
        raise KeyError(audit_id)

    def _replace(self, audit_id: str, event: AuditEvent) -> None:
        for i, current in enumerate(self._events):
            if current.audit_id == audit_id:
                self._events[i] = event; return
        raise KeyError(audit_id)
