from __future__ import annotations

import base64
import binascii
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from services.ai.image_intelligence import get_image_intelligence_service
from verideploy.multimodal.image_intelligence import (
    VisualAnalysisResult,
    ImageAnalysisType,
    ImageDetail,
    ImageIntelligenceService,
    ImageProvenance,
)

router = APIRouter(prefix="/internal/v1/ai/images", tags=["ai-images-internal"])


class ImageAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    correlation_id: str = Field(min_length=1, max_length=128)
    source_object_ref: str = Field(min_length=1, max_length=1024)
    source_type: Literal["uploaded_image", "document_page", "video_frame", "synthetic_fixture"]
    analysis_type: ImageAnalysisType
    image_base64: str = Field(min_length=4, max_length=40_000_000)
    detail: ImageDetail | None = None
    page_number: int | None = Field(default=None, ge=1)
    timecode_seconds: float | None = Field(default=None, ge=0)


class ImageAnalysisResponse(BaseModel):
    provenance: ImageProvenance
    analysis: VisualAnalysisResult


def _authorize(service_name: str) -> None:
    if service_name not in {"verideploy-gateway", "verideploy-multimodal-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


@router.post("/analyze", response_model=ImageAnalysisResponse)
async def analyze_image(
    payload: ImageAnalysisRequest,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    service: ImageIntelligenceService = Depends(get_image_intelligence_service),
) -> ImageAnalysisResponse:
    _authorize(x_internal_service)
    if x_tenant_id is not None and x_tenant_id != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope mismatch")
    try:
        raw = base64.b64decode(payload.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid base64 image payload") from exc
    try:
        provenance, analysis = await service.analyze(
            tenant_id=payload.tenant_id,
            correlation_id=payload.correlation_id,
            source_object_ref=payload.source_object_ref,
            source_type=payload.source_type,
            raw_bytes=raw,
            analysis_type=payload.analysis_type,
            requested_detail=payload.detail,
            page_number=payload.page_number,
            timecode_seconds=payload.timecode_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ImageAnalysisResponse(provenance=provenance, analysis=analysis)
