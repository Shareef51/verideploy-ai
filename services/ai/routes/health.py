import asyncio
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from services.ai.dependencies import RuntimeDependencies, get_runtime_dependencies
from services.ai.platform_readiness import probe_all
from verideploy import __version__

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "ready", "degraded"]
    service: str
    version: str
    timestamp: datetime
    checks: dict[str, str] = Field(default_factory=dict)


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="verideploy-ai-service",
        version=__version__,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready", response_model=HealthResponse)
async def ready(response: Response, deps: RuntimeDependencies = Depends(get_runtime_dependencies)) -> HealthResponse:
    checks = {"configuration": "ok" if deps.settings.app_name else "failed"}
    if deps.settings.platform_dependency_readiness_enabled:
        results = await asyncio.to_thread(probe_all, deps.settings)
        checks.update({item.name: "ok" if item.ok else "failed" for item in results})
    ready_state = all(value == "ok" for value in checks.values())
    if not ready_state:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ready" if ready_state else "degraded",
        service="verideploy-ai-service",
        version=__version__,
        timestamp=datetime.now(timezone.utc),
        checks=checks,
    )
