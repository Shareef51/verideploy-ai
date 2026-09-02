from __future__ import annotations
from functools import lru_cache
from services.ai.hallucination_protection import get_hallucination_protector
from services.ai.self_corrective_rag import get_self_corrective_rag
from verideploy.config import get_settings
from verideploy.database.factory import create_database_manager
from verideploy.rag.citations.repository import PostgresCitationRepository,PostgresCitationSourceRepository
from verideploy.rag.citations.service import CitationService

@lru_cache
def get_citation_service()->CitationService:
    settings=get_settings()
    if not settings.database_url.startswith("postgresql"):raise RuntimeError("citation runtime requires PostgreSQL")
    db=create_database_manager(settings)
    protector=get_hallucination_protector(); corrective=get_self_corrective_rag()
    return CitationService(hallucination_runs=protector.repository,source_runs=corrective.repository,repository=PostgresCitationRepository(db),sources=PostgresCitationSourceRepository(db),supported_threshold=settings.hallucination_supported_threshold,uncertain_threshold=settings.hallucination_uncertain_threshold)
