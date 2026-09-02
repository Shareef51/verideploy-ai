from __future__ import annotations

from functools import lru_cache

from services.ai.ai_gateway import get_ai_gateway
from verideploy.config import get_settings
from verideploy.multimodal.image_intelligence import (
    ImageDetail,
    ImageIntelligenceService,
    ImagePreparationPolicy,
    SecureImagePreparer,
)


@lru_cache
def get_image_intelligence_service() -> ImageIntelligenceService:
    settings = get_settings()
    policy = ImagePreparationPolicy(
        max_input_bytes=settings.max_image_upload_bytes,
        max_pixels=settings.ai_image_max_pixels,
        max_side=settings.ai_image_max_side,
        allow_original_detail=settings.ai_image_allow_original_detail,
        default_detail=ImageDetail(settings.ai_image_default_detail),
    )
    return ImageIntelligenceService(get_ai_gateway(), SecureImagePreparer(policy))
