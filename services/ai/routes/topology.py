from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from services.ai.topology import get_topology_service
from verideploy.topology.schemas import TopologySnapshot
from verideploy.topology.service import TopologyService

router = APIRouter(prefix="/internal/v1/topology", tags=["topology-internal"])


def _trusted(service: str) -> None:
    if service not in {"verideploy-gateway", "verideploy-investigation-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


@router.get("/nexuspay", response_model=TopologySnapshot)
def nexuspay_topology(
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(...),
    service: TopologyService = Depends(get_topology_service),
) -> TopologySnapshot:
    _trusted(x_internal_service)
    snapshot = service.get(tenant_id=x_tenant_id, company_slug="nexuspay")
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NexusPay topology is not seeded for this tenant")
    return snapshot
