from __future__ import annotations

import os
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status

from services.ai.routes.investigations import get_investigation_service
from verideploy.config import get_settings
from verideploy.postmortems.repository import SqlAlchemyPostmortemRepository
from verideploy.postmortems.schemas import PostmortemExport, PostmortemRecord, ReviewPostmortemCommand
from verideploy.postmortems.service import PostmortemEligibilityError, PostmortemService

router = APIRouter(prefix="/internal/v1/postmortems", tags=["postmortems"])


def _authorize(service_name: str) -> None:
    if service_name != "verideploy-gateway":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


def _runtime_database_url() -> tuple[str, bool]:
    configured = os.getenv("POSTMORTEM_DATABASE_URL") or os.getenv("INVESTIGATION_DATABASE_URL")
    if configured:
        return configured, configured.startswith("sqlite")
    settings = get_settings()
    return settings.database_url, settings.app_env in {"development", "test"}


@lru_cache
def get_postmortem_service() -> PostmortemService:
    url, create_schema = _runtime_database_url()
    return PostmortemService(SqlAlchemyPostmortemRepository(url, create_schema=create_schema), get_investigation_service())


@router.get("", response_model=list[PostmortemRecord])
def list_postmortems(x_tenant_id: UUID = Header(), x_internal_service: str = Header(default=""), limit: int = Query(default=50, ge=1, le=100)) -> list[PostmortemRecord]:
    _authorize(x_internal_service)
    return get_postmortem_service().list(x_tenant_id, limit)


@router.get("/{postmortem_id}", response_model=PostmortemRecord)
def get_postmortem(postmortem_id: UUID, x_tenant_id: UUID = Header(), x_internal_service: str = Header(default="")) -> PostmortemRecord:
    _authorize(x_internal_service)
    record = get_postmortem_service().get(x_tenant_id, postmortem_id)
    if record is None:
        raise HTTPException(status_code=404, detail="postmortem not found")
    return record


@router.post("/{postmortem_id}/review", response_model=PostmortemRecord)
def review_postmortem(postmortem_id: UUID, command: ReviewPostmortemCommand, x_tenant_id: UUID = Header(), x_internal_service: str = Header(default="")) -> PostmortemRecord:
    _authorize(x_internal_service)
    if command.postmortem_id != postmortem_id or command.tenant_id != x_tenant_id:
        raise HTTPException(status_code=400, detail="request identity mismatch")
    try:
        return get_postmortem_service().review(command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="postmortem not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{postmortem_id}/export", response_model=PostmortemExport)
def export_postmortem(postmortem_id: UUID, x_tenant_id: UUID = Header(), x_internal_service: str = Header(default=""), format: str = Query(default="markdown")) -> PostmortemExport:
    _authorize(x_internal_service)
    try:
        return get_postmortem_service().export(x_tenant_id, postmortem_id, format)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="postmortem not found") from exc
    except (ValueError, PostmortemEligibilityError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
