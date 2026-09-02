from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from services.ai.langsmith import get_langsmith_observer

router = APIRouter(prefix="/internal/v1/langsmith", tags=["internal-langsmith"])
_TRUSTED = {"verideploy-gateway", "verideploy-investigation-worker"}


@router.get("/status")
def status(x_internal_service: str | None = Header(default=None)):
    if x_internal_service not in _TRUSTED:
        raise HTTPException(status_code=401, detail="trusted internal service required")
    return get_langsmith_observer().status.model_dump(mode="json")
