from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from services.ai.fusion import get_multimodal_fusion_service
from verideploy.rag.fusion.schemas import MultimodalFusionRequest, MultimodalFusionResult
from verideploy.rag.fusion.service import MultimodalEvidenceFusion

router = APIRouter(prefix="/internal/v1/rag", tags=["rag-fusion-internal"])


def _authorize(service_name: str) -> None:
    if service_name not in {"verideploy-gateway", "verideploy-investigation-worker", "verideploy-multimodal-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


@router.post("/fuse", response_model=MultimodalFusionResult)
def fuse_evidence(
    payload: MultimodalFusionRequest,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    service: MultimodalEvidenceFusion = Depends(get_multimodal_fusion_service),
) -> MultimodalFusionResult:
    _authorize(x_internal_service)
    if x_tenant_id is not None and x_tenant_id != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope mismatch")
    return service.fuse(payload)
