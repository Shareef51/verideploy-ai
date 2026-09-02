from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from services.ai.evidence import get_evidence_service
from verideploy.evidence.repository import EvidenceConflictError, EvidenceNotFoundError, EvidenceTenantViolation
from verideploy.evidence.schemas import EvidenceCreate, EvidenceLineage, EvidenceRecord, EvidenceVersionCreate
from verideploy.evidence.service import EvidenceService

router = APIRouter(prefix="/internal/v1/evidence", tags=["evidence-internal"])


def _trusted(service: str) -> None:
    if service not in {"verideploy-gateway", "verideploy-investigation-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


def _tenant(header_tenant: UUID, body_tenant: UUID) -> None:
    if header_tenant != body_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, EvidenceNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, EvidenceTenantViolation):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, EvidenceConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc


@router.post("", response_model=EvidenceRecord, status_code=status.HTTP_201_CREATED)
def create_evidence(
    payload: EvidenceCreate,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(...),
    service: EvidenceService = Depends(get_evidence_service),
) -> EvidenceRecord:
    _trusted(x_internal_service); _tenant(x_tenant_id, payload.tenant_id)
    try: return service.create(payload)
    except (EvidenceNotFoundError, EvidenceTenantViolation, EvidenceConflictError) as exc: raise _translate(exc)


@router.post("/{evidence_id}/versions", response_model=EvidenceRecord, status_code=status.HTTP_201_CREATED)
def create_evidence_version(
    evidence_id: UUID,
    payload: EvidenceVersionCreate,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(...),
    service: EvidenceService = Depends(get_evidence_service),
) -> EvidenceRecord:
    _trusted(x_internal_service); _tenant(x_tenant_id, payload.tenant_id)
    if evidence_id != payload.evidence_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="path evidence_id does not match request")
    try: return service.create_version(payload)
    except (EvidenceNotFoundError, EvidenceTenantViolation, EvidenceConflictError) as exc: raise _translate(exc)


@router.get("/records/{record_id}", response_model=EvidenceRecord)
def get_record(
    record_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(...),
    service: EvidenceService = Depends(get_evidence_service),
) -> EvidenceRecord:
    _trusted(x_internal_service)
    try: return service.get(tenant_id=x_tenant_id, record_id=record_id)
    except EvidenceNotFoundError as exc: raise _translate(exc)


@router.get("/{evidence_id}/latest", response_model=EvidenceRecord)
def get_latest(
    evidence_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(...),
    service: EvidenceService = Depends(get_evidence_service),
) -> EvidenceRecord:
    _trusted(x_internal_service)
    try: return service.latest(tenant_id=x_tenant_id, evidence_id=evidence_id)
    except EvidenceNotFoundError as exc: raise _translate(exc)


@router.get("/{evidence_id}/versions", response_model=list[EvidenceRecord])
def list_versions(
    evidence_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(...),
    service: EvidenceService = Depends(get_evidence_service),
) -> list[EvidenceRecord]:
    _trusted(x_internal_service)
    return list(service.versions(tenant_id=x_tenant_id, evidence_id=evidence_id))


@router.get("/records/{record_id}/lineage", response_model=EvidenceLineage)
def get_lineage(
    record_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(...),
    service: EvidenceService = Depends(get_evidence_service),
) -> EvidenceLineage:
    _trusted(x_internal_service)
    try: return service.lineage(tenant_id=x_tenant_id, record_id=record_id)
    except EvidenceNotFoundError as exc: raise _translate(exc)
