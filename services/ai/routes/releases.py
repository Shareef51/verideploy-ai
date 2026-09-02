from __future__ import annotations

import os
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status

from verideploy.config import get_settings
from verideploy.releases.repository import SqlAlchemyReleaseRiskRepository
from verideploy.releases.schemas import ReleaseRiskRecord
from verideploy.releases.service import ReleaseRiskService

router = APIRouter(prefix="/internal/v1/releases", tags=["release-risk"])


def _runtime_database_url() -> tuple[str, bool]:
    configured = os.getenv("RELEASE_RISK_DATABASE_URL")
    if configured:
        return configured, configured.startswith("sqlite")
    settings = get_settings()
    return settings.database_url, settings.app_env in {"development", "test"}


@lru_cache
def get_release_risk_service() -> ReleaseRiskService:
    url, create_schema = _runtime_database_url()
    repository = SqlAlchemyReleaseRiskRepository(url, create_schema=create_schema)
    return ReleaseRiskService(repository, get_settings().require_human_approval_at_risk_score)


@router.get("/assessments", response_model=list[ReleaseRiskRecord])
def list_assessments(
    x_tenant_id: UUID = Header(),
    x_internal_service: str = Header(default=""),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ReleaseRiskRecord]:
    if x_internal_service != "verideploy-gateway":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")
    return get_release_risk_service().list_recent(x_tenant_id, limit)


@router.get("/assessments/{assessment_id}", response_model=ReleaseRiskRecord)
def get_assessment(
    assessment_id: UUID,
    x_tenant_id: UUID = Header(),
    x_internal_service: str = Header(default=""),
) -> ReleaseRiskRecord:
    if x_internal_service != "verideploy-gateway":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")
    record = get_release_risk_service().get(x_tenant_id, assessment_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="release risk assessment not found")
    return record
