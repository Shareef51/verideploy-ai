from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from services.ai.approvals import get_approval_service
from verideploy.approvals.repository import ApprovalConflictError
from verideploy.approvals.schemas import (
    ApprovalAuthorization,
    ApprovalEvent,
    ApprovalRequest,
    ApprovalRequestCreate,
    DecisionCommand,
    DelegationCommand,
    ReviewerContext,
)
from verideploy.approvals.service import ApprovalExpiredError, ApprovalPermissionError, HumanApprovalService

router = APIRouter(prefix="/internal/v1/approvals", tags=["approvals-internal"])
TRUSTED = {"verideploy-gateway", "verideploy-investigation-worker"}


def _trusted(service: str) -> None:
    if service not in TRUSTED:
        raise HTTPException(status_code=401, detail="trusted service identity required")


def _tenant(header: UUID | None) -> UUID:
    if header is None:
        raise HTTPException(status_code=400, detail="tenant header required")
    return header


@router.post("", response_model=ApprovalRequest)
def create_approval(
    payload: ApprovalRequestCreate,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    service: HumanApprovalService = Depends(get_approval_service),
):
    _trusted(x_internal_service)
    tenant_id = _tenant(x_tenant_id)
    if payload.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant scope mismatch")
    try:
        return service.request_review(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/queue", response_model=list[ApprovalRequest])
def queue(
    reviewer_id: str | None = Query(default=None),
    reviewer_roles: str | None = Query(default=None),
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    service: HumanApprovalService = Depends(get_approval_service),
):
    _trusted(x_internal_service)
    tenant_id = _tenant(x_tenant_id)
    reviewer = None
    if reviewer_id:
        reviewer = ReviewerContext(reviewer_id=reviewer_id, roles=frozenset(x.strip() for x in (reviewer_roles or "").split(",") if x.strip()))
    return service.queue(tenant_id=tenant_id, reviewer=reviewer)


@router.get("/{approval_id}", response_model=ApprovalRequest)
def get_approval(
    approval_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    service: HumanApprovalService = Depends(get_approval_service),
):
    _trusted(x_internal_service)
    item = service.get(tenant_id=_tenant(x_tenant_id), approval_id=approval_id)
    if item is None:
        raise HTTPException(status_code=404, detail="approval not found")
    return item


@router.get("/{approval_id}/events", response_model=list[ApprovalEvent])
def events(
    approval_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    service: HumanApprovalService = Depends(get_approval_service),
):
    _trusted(x_internal_service)
    return service.events(tenant_id=_tenant(x_tenant_id), approval_id=approval_id)


@router.post("/{approval_id}/decision", response_model=ApprovalRequest)
def decide(
    approval_id: UUID,
    command: DecisionCommand,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    service: HumanApprovalService = Depends(get_approval_service),
):
    _trusted(x_internal_service)
    tenant_id = _tenant(x_tenant_id)
    if command.tenant_id != tenant_id or command.approval_id != approval_id:
        raise HTTPException(status_code=403, detail="approval/tenant scope mismatch")
    try:
        return service.decide(command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApprovalExpiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{approval_id}/delegate", response_model=ApprovalRequest)
def delegate(
    approval_id: UUID,
    command: DelegationCommand,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    service: HumanApprovalService = Depends(get_approval_service),
):
    _trusted(x_internal_service)
    tenant_id = _tenant(x_tenant_id)
    if command.tenant_id != tenant_id or command.approval_id != approval_id:
        raise HTTPException(status_code=403, detail="approval/tenant scope mismatch")
    try:
        return service.delegate(command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApprovalConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{approval_id}/authorization", response_model=ApprovalAuthorization)
def authorization(
    approval_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    service: HumanApprovalService = Depends(get_approval_service),
):
    _trusted(x_internal_service)
    return service.authorize_action(tenant_id=_tenant(x_tenant_id), approval_id=approval_id)
