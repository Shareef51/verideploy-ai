from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
import copy
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.evidence.schemas import (
    ConfidenceInputs,
    EvidenceKind,
    EvidenceParent,
    EvidenceRecord,
    ObjectReference,
    ParentRelation,
    Provenance,
    RetentionPolicy,
)


class EvidenceConflictError(RuntimeError): pass
class EvidenceNotFoundError(LookupError): pass
class EvidenceTenantViolation(PermissionError): pass


class EvidenceRepository(ABC):
    @abstractmethod
    def insert(self, record: EvidenceRecord) -> EvidenceRecord: ...
    @abstractmethod
    def get_record(self, *, tenant_id: UUID, record_id: UUID) -> EvidenceRecord | None: ...
    @abstractmethod
    def get_latest(self, *, tenant_id: UUID, evidence_id: UUID) -> EvidenceRecord | None: ...
    @abstractmethod
    def list_versions(self, *, tenant_id: UUID, evidence_id: UUID) -> tuple[EvidenceRecord, ...]: ...
    @abstractmethod
    def children_of(self, *, tenant_id: UUID, record_id: UUID) -> tuple[EvidenceRecord, ...]: ...


class InMemoryEvidenceRepository(EvidenceRepository):
    def __init__(self) -> None:
        self._records: dict[UUID, EvidenceRecord] = {}
        self._versions: dict[tuple[UUID, UUID], list[UUID]] = defaultdict(list)
        self._children: dict[UUID, list[UUID]] = defaultdict(list)

    def insert(self, record: EvidenceRecord) -> EvidenceRecord:
        if record.record_id in self._records:
            existing = self._records[record.record_id]
            if existing == record:
                return existing
            raise EvidenceConflictError("record_id already exists")
        key = (record.tenant_id, record.evidence_id)
        versions = [self._records[rid] for rid in self._versions[key]]
        if any(r.version == record.version for r in versions):
            raise EvidenceConflictError("evidence version already exists")
        if versions and record.version != max(r.version for r in versions) + 1:
            raise EvidenceConflictError("evidence versions must be contiguous")
        if not versions and record.version != 1:
            raise EvidenceConflictError("first evidence version must be 1")
        for parent in record.parents:
            p = self._records.get(parent.parent_record_id)
            if p is None:
                raise EvidenceNotFoundError("parent evidence record not found")
            if p.tenant_id != record.tenant_id:
                raise EvidenceTenantViolation("parent evidence belongs to another tenant")
        stored = record.model_copy(deep=True)
        self._records[record.record_id] = stored
        self._versions[key].append(record.record_id)
        for parent in record.parents:
            self._children[parent.parent_record_id].append(record.record_id)
        return stored.model_copy(deep=True)

    def get_record(self, *, tenant_id: UUID, record_id: UUID) -> EvidenceRecord | None:
        row = self._records.get(record_id)
        return row.model_copy(deep=True) if row is not None and row.tenant_id == tenant_id else None

    def get_latest(self, *, tenant_id: UUID, evidence_id: UUID) -> EvidenceRecord | None:
        rows = self.list_versions(tenant_id=tenant_id, evidence_id=evidence_id)
        return rows[-1] if rows else None

    def list_versions(self, *, tenant_id: UUID, evidence_id: UUID) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records[rid].model_copy(deep=True) for rid in self._versions.get((tenant_id, evidence_id), []))

    def children_of(self, *, tenant_id: UUID, record_id: UUID) -> tuple[EvidenceRecord, ...]:
        return tuple(r.model_copy(deep=True) for rid in self._children.get(record_id, []) if (r := self._records[rid]).tenant_id == tenant_id)


def _record_from_mapping(row: dict[str, Any], parents: tuple[EvidenceParent, ...]) -> EvidenceRecord:
    return EvidenceRecord.model_validate({
        "record_id": row["record_id"], "evidence_id": row["evidence_id"], "tenant_id": row["tenant_id"],
        "version": row["version"], "is_derived": row["is_derived"], "kind": row["kind"], "content": row["content"], "content_sha256": row["content_sha256"],
        "object_reference": row["object_reference"], "confidence_inputs": row["confidence_inputs"],
        "provenance": row["provenance"], "retention": row["retention"], "parents": parents, "created_at": row["created_at"],
    })


class PostgresEvidenceRepository(EvidenceRepository):
    def __init__(self, db: DatabaseManager) -> None:
        if db.engine.dialect.name != "postgresql":
            raise ValueError("PostgresEvidenceRepository requires PostgreSQL")
        self.db = db

    def _parents(self, session: Any, record_id: UUID) -> tuple[EvidenceParent, ...]:
        rows = session.execute(text("SELECT parent_record_id, relation FROM evidence_parent_links WHERE child_record_id=:rid ORDER BY parent_record_id"), {"rid": str(record_id)}).mappings()
        return tuple(EvidenceParent.model_validate(dict(r)) for r in rows)

    def insert(self, record: EvidenceRecord) -> EvidenceRecord:
        with self.db.tenant_session(record.tenant_id, statement_timeout_ms=15_000) as session:
            for parent in record.parents:
                found = session.execute(text("SELECT tenant_id FROM evidence_versions WHERE record_id=:rid"), {"rid": str(parent.parent_record_id)}).scalar_one_or_none()
                if found is None:
                    raise EvidenceNotFoundError("parent evidence record not found")
                if UUID(str(found)) != record.tenant_id:
                    raise EvidenceTenantViolation("parent evidence belongs to another tenant")
            payload = record.model_dump(mode="json")
            session.execute(text("""
                INSERT INTO evidence_versions
                (record_id,evidence_id,tenant_id,version,is_derived,kind,content,content_sha256,object_reference,confidence_inputs,provenance,retention,created_at)
                VALUES (:record_id,:evidence_id,:tenant_id,:version,:is_derived,:kind,CAST(:content AS jsonb),:content_sha256,CAST(:object_reference AS jsonb),CAST(:confidence_inputs AS jsonb),CAST(:provenance AS jsonb),CAST(:retention AS jsonb),:created_at)
            """), {
                "record_id": str(record.record_id), "evidence_id": str(record.evidence_id), "tenant_id": str(record.tenant_id),
                "version": record.version, "is_derived": record.is_derived, "kind": record.kind.value, "content": __import__("json").dumps(payload["content"]),
                "content_sha256": record.content_sha256, "object_reference": __import__("json").dumps(payload["object_reference"]) if payload["object_reference"] else None,
                "confidence_inputs": __import__("json").dumps(payload["confidence_inputs"]), "provenance": __import__("json").dumps(payload["provenance"]),
                "retention": __import__("json").dumps(payload["retention"]), "created_at": record.created_at,
            })
            for parent in record.parents:
                session.execute(text("INSERT INTO evidence_parent_links (tenant_id,parent_record_id,child_record_id,relation) VALUES (:tenant,:parent,:child,:relation)"), {
                    "tenant": str(record.tenant_id), "parent": str(parent.parent_record_id), "child": str(record.record_id), "relation": parent.relation.value,
                })
            session.commit()
        return record

    def get_record(self, *, tenant_id: UUID, record_id: UUID) -> EvidenceRecord | None:
        with self.db.tenant_session(tenant_id) as session:
            row = session.execute(text("SELECT * FROM evidence_versions WHERE tenant_id=:tenant AND record_id=:rid"), {"tenant": str(tenant_id), "rid": str(record_id)}).mappings().first()
            return _record_from_mapping(dict(row), self._parents(session, record_id)) if row else None

    def get_latest(self, *, tenant_id: UUID, evidence_id: UUID) -> EvidenceRecord | None:
        with self.db.tenant_session(tenant_id) as session:
            row = session.execute(text("SELECT * FROM evidence_versions WHERE tenant_id=:tenant AND evidence_id=:eid ORDER BY version DESC LIMIT 1"), {"tenant": str(tenant_id), "eid": str(evidence_id)}).mappings().first()
            return _record_from_mapping(dict(row), self._parents(session, row["record_id"])) if row else None

    def list_versions(self, *, tenant_id: UUID, evidence_id: UUID) -> tuple[EvidenceRecord, ...]:
        with self.db.tenant_session(tenant_id) as session:
            rows = session.execute(text("SELECT * FROM evidence_versions WHERE tenant_id=:tenant AND evidence_id=:eid ORDER BY version"), {"tenant": str(tenant_id), "eid": str(evidence_id)}).mappings().all()
            return tuple(_record_from_mapping(dict(row), self._parents(session, row["record_id"])) for row in rows)

    def children_of(self, *, tenant_id: UUID, record_id: UUID) -> tuple[EvidenceRecord, ...]:
        with self.db.tenant_session(tenant_id) as session:
            rows = session.execute(text("""
                SELECT e.* FROM evidence_versions e
                JOIN evidence_parent_links l ON l.child_record_id=e.record_id
                WHERE l.tenant_id=:tenant AND l.parent_record_id=:rid ORDER BY e.created_at,e.record_id
            """), {"tenant": str(tenant_id), "rid": str(record_id)}).mappings().all()
            return tuple(_record_from_mapping(dict(row), self._parents(session, row["record_id"])) for row in rows)
