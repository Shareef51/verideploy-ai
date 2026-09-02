from __future__ import annotations
from functools import lru_cache

from services.ai.self_corrective_rag import get_self_corrective_rag
from verideploy.config import get_settings
from verideploy.database.factory import create_database_manager
from verideploy.rag.hallucination.repository import PostgresHallucinationProtectionRepository
from verideploy.rag.hallucination.service import HallucinationProtector


@lru_cache
def get_hallucination_protector() -> HallucinationProtector:
    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        raise RuntimeError("hallucination protection runtime requires PostgreSQL")
    db = create_database_manager(settings)
    controller = get_self_corrective_rag()
    return HallucinationProtector(
        source_runs=controller.repository,
        repository=PostgresHallucinationProtectionRepository(db),
        supported_threshold=settings.hallucination_supported_threshold,
        uncertain_threshold=settings.hallucination_uncertain_threshold,
        contradiction_threshold=settings.hallucination_contradiction_threshold,
        protected_unsupported_material_threshold=settings.hallucination_unsupported_material_threshold,
    )
