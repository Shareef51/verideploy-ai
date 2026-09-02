from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from services.ai.video_evidence import get_video_evidence_service
from verideploy.multimodal.video_evidence import VideoEvidenceRecord, VideoEvidenceService

router = APIRouter(prefix="/internal/v1/video/evidence", tags=["video-evidence-internal"])


def _authorize(service_name: str) -> None:
    if service_name not in {"verideploy-gateway", "verideploy-multimodal-worker", "verideploy-investigation-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


@router.get("/{video_job_id}", response_model=VideoEvidenceRecord)
def get_video_evidence(
    video_job_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(),
    service: VideoEvidenceService = Depends(get_video_evidence_service),
) -> VideoEvidenceRecord:
    _authorize(x_internal_service)
    record = service.repository.get(x_tenant_id, video_job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="video evidence job not found")
    return record
