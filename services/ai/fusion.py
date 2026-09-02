from functools import lru_cache

from verideploy.config import get_settings
from verideploy.rag.fusion.schemas import FusionBudgets
from verideploy.rag.fusion.service import MultimodalEvidenceFusion


@lru_cache
def get_multimodal_fusion_service() -> MultimodalEvidenceFusion:
    settings = get_settings()
    return MultimodalEvidenceFusion(
        FusionBudgets(
            max_context_tokens=settings.rag_context_max_tokens,
            max_images=settings.rag_context_max_images,
            max_total_evidence=settings.rag_context_max_evidence,
            max_per_channel=settings.rag_context_max_per_channel,
        )
    )
