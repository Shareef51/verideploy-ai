from __future__ import annotations
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict
from services.ai.integrations import get_engineering_integrations
from verideploy.integrations.factory import EngineeringIntegrations

router=APIRouter(prefix="/internal/v1/integrations", tags=["integrations-internal"])

class IntegrationReadiness(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source: str
    configured: bool

class IntegrationReadinessResponse(BaseModel):
    model_config=ConfigDict(extra="forbid")
    integrations: list[IntegrationReadiness]


def _trusted(service: str) -> None:
    if service not in {"verideploy-gateway","verideploy-investigation-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="trusted service identity required")

@router.get("/status", response_model=IntegrationReadinessResponse)
async def status_endpoint(x_internal_service: str=Header(default=""), integrations: EngineeringIntegrations=Depends(get_engineering_integrations)) -> IntegrationReadinessResponse:
    _trusted(x_internal_service)
    rows=[
        IntegrationReadiness(source="github",configured=integrations.github.client.configured),
        IntegrationReadiness(source="jira",configured=integrations.jira.client.configured),
        IntegrationReadiness(source="prometheus",configured=integrations.prometheus.client.configured),
        IntegrationReadiness(source="grafana",configured=integrations.grafana.client.configured),
        IntegrationReadiness(source="trace",configured=integrations.traces.client.configured),
        IntegrationReadiness(source="log",configured=integrations.logs.client.configured),
    ]
    return IntegrationReadinessResponse(integrations=rows)
