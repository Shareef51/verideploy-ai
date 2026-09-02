from __future__ import annotations

import os
import base64
import json
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status

from verideploy.config import get_settings
from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.projection import InvestigationProjection
from verideploy.investigations.schemas import InvestigationEvent, InvestigationList, InvestigationRecord
from pydantic import BaseModel
from verideploy.investigations.service import InvestigationService

router = APIRouter(prefix="/internal/v1/investigations", tags=["investigations"])


def _runtime_database_url() -> tuple[str, bool]:
    configured = os.getenv("INVESTIGATION_DATABASE_URL")
    if configured:
        return configured, configured.startswith("sqlite")
    settings = get_settings()
    return settings.database_url, settings.app_env in {"development", "test"}


@lru_cache
def get_investigation_service() -> InvestigationService:
    url, create_schema = _runtime_database_url()
    return InvestigationService(SqlAlchemyInvestigationRepository(url, create_schema=create_schema))


def _authorize(service_name: str) -> None:
    if service_name != "verideploy-gateway":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


@router.get("", response_model=InvestigationList)
def list_investigations(
    x_tenant_id: UUID = Header(), x_internal_service: str = Header(default=""), limit: int = Query(default=50, ge=1, le=100),
) -> InvestigationList:
    _authorize(x_internal_service)
    return InvestigationList(items=get_investigation_service().list(x_tenant_id, limit=limit))

class InvestigationPage(BaseModel):
    items: list[InvestigationRecord]
    next_cursor: str | None = None

def _decode_cursor(cursor: str | None) -> int:
    if not cursor: return 0
    try:
        payload=json.loads(base64.urlsafe_b64decode(cursor.encode()+b"="*((4-len(cursor)%4)%4)).decode())
        offset=int(payload["offset"]); assert 0 <= offset <= 10000; return offset
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid pagination cursor") from exc

def _encode_cursor(offset:int)->str:
    return base64.urlsafe_b64encode(json.dumps({"offset":offset},separators=(",",":")).encode()).decode().rstrip("=")

@router.get("/page", response_model=InvestigationPage)
def page_investigations(
    x_tenant_id: UUID = Header(), x_internal_service: str = Header(default=""), limit: int = Query(default=25, ge=1, le=100), cursor: str | None = Query(default=None),
) -> InvestigationPage:
    _authorize(x_internal_service); offset=_decode_cursor(cursor)
    rows=get_investigation_service().list(x_tenant_id, limit=min(10001, offset+limit+1))
    page=rows[offset:offset+limit]; more=len(rows)>offset+limit
    return InvestigationPage(items=page,next_cursor=_encode_cursor(offset+limit) if more else None)


@router.get("/{investigation_id}", response_model=InvestigationRecord)
def get_investigation(investigation_id: UUID, x_tenant_id: UUID = Header(), x_internal_service: str = Header(default="")) -> InvestigationRecord:
    _authorize(x_internal_service)
    record = get_investigation_service().get(x_tenant_id, investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return record


@router.get("/{investigation_id}/view", response_model=InvestigationProjection)
def get_investigation_view(
    investigation_id: UUID, x_tenant_id: UUID = Header(), x_internal_service: str = Header(default=""),
) -> InvestigationProjection:
    _authorize(x_internal_service)
    try:
        return get_investigation_service().projection(x_tenant_id, investigation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="investigation not found") from exc


@router.get("/{investigation_id}/events", response_model=list[InvestigationEvent])
def get_investigation_events(
    investigation_id: UUID,
    x_tenant_id: UUID = Header(),
    x_internal_service: str = Header(default=""),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[InvestigationEvent]:
    _authorize(x_internal_service)
    try:
        return get_investigation_service().events(x_tenant_id, investigation_id, after_sequence=after_sequence, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="investigation not found") from exc
