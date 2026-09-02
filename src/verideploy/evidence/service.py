from __future__ import annotations

import uuid
from uuid import UUID

from verideploy.evidence.repository import EvidenceConflictError, EvidenceNotFoundError, EvidenceRepository, EvidenceTenantViolation
from verideploy.evidence.schemas import (
    EvidenceCreate, EvidenceLineage, EvidenceParent, EvidenceRecord, EvidenceVersionCreate, ParentRelation,
    canonical_content_sha256, utcnow,
)


class EvidenceService:
    def __init__(self, repository: EvidenceRepository) -> None:
        self.repository = repository

    @staticmethod
    def _record_id(evidence_id: UUID, version: int, content_sha256: str) -> UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"verideploy:evidence:{evidence_id}:v{version}:{content_sha256}")

    @staticmethod
    def _validate_retention(retention) -> None:
        if retention.retain_until <= utcnow():
            raise EvidenceConflictError("retention retain_until must be in the future")

    def create(self, request: EvidenceCreate) -> EvidenceRecord:
        if self.repository.get_latest(tenant_id=request.tenant_id, evidence_id=request.evidence_id) is not None:
            raise EvidenceConflictError("evidence_id already exists; create a new version instead")
        self._validate_retention(request.retention)
        self._validate_parents(request.tenant_id, request.parents)
        digest = canonical_content_sha256(request.content)
        record = EvidenceRecord(
            record_id=self._record_id(request.evidence_id, 1, digest), evidence_id=request.evidence_id, tenant_id=request.tenant_id,
            version=1, is_derived=request.derived, kind=request.kind, content=request.content, content_sha256=digest, object_reference=request.object_reference,
            confidence_inputs=request.confidence_inputs, provenance=request.provenance, retention=request.retention,
            parents=request.parents, created_at=utcnow(),
        )
        return self.repository.insert(record)

    def create_version(self, request: EvidenceVersionCreate) -> EvidenceRecord:
        previous = self.repository.get_record(tenant_id=request.tenant_id, record_id=request.previous_record_id)
        if previous is None:
            raise EvidenceNotFoundError("previous evidence version not found")
        if previous.evidence_id != request.evidence_id:
            raise EvidenceConflictError("previous_record_id belongs to another evidence_id")
        latest = self.repository.get_latest(tenant_id=request.tenant_id, evidence_id=request.evidence_id)
        if latest is None or latest.record_id != previous.record_id:
            raise EvidenceConflictError("new versions must derive from the latest evidence version")
        self._validate_retention(request.retention)
        self._validate_parents(request.tenant_id, request.additional_parents)
        digest = canonical_content_sha256(request.content)
        version = previous.version + 1
        parents = (EvidenceParent(parent_record_id=previous.record_id, relation=ParentRelation.VERSION_OF),) + request.additional_parents
        record = EvidenceRecord(
            record_id=self._record_id(request.evidence_id, version, digest), evidence_id=request.evidence_id, tenant_id=request.tenant_id,
            version=version, is_derived=True, kind=previous.kind, content=request.content, content_sha256=digest, object_reference=request.object_reference,
            confidence_inputs=request.confidence_inputs, provenance=request.provenance, retention=request.retention,
            parents=parents, created_at=utcnow(),
        )
        return self.repository.insert(record)

    def _validate_parents(self, tenant_id: UUID, parents: tuple[EvidenceParent, ...]) -> None:
        for parent in parents:
            row = self.repository.get_record(tenant_id=tenant_id, record_id=parent.parent_record_id)
            if row is None:
                raise EvidenceNotFoundError("parent evidence record not found in tenant scope")

    def get(self, *, tenant_id: UUID, record_id: UUID) -> EvidenceRecord:
        row = self.repository.get_record(tenant_id=tenant_id, record_id=record_id)
        if row is None: raise EvidenceNotFoundError("evidence record not found")
        return row

    def latest(self, *, tenant_id: UUID, evidence_id: UUID) -> EvidenceRecord:
        row = self.repository.get_latest(tenant_id=tenant_id, evidence_id=evidence_id)
        if row is None: raise EvidenceNotFoundError("evidence not found")
        return row

    def versions(self, *, tenant_id: UUID, evidence_id: UUID) -> tuple[EvidenceRecord, ...]:
        return self.repository.list_versions(tenant_id=tenant_id, evidence_id=evidence_id)

    def lineage(self, *, tenant_id: UUID, record_id: UUID) -> EvidenceLineage:
        record = self.get(tenant_id=tenant_id, record_id=record_id)
        parents = tuple(self.get(tenant_id=tenant_id, record_id=p.parent_record_id) for p in record.parents)
        children = self.repository.children_of(tenant_id=tenant_id, record_id=record_id)
        return EvidenceLineage(record=record, parents=parents, children=children)
