from __future__ import annotations
from functools import lru_cache

from services.ai.retrieval_pipeline import get_retrieval_pipeline
from verideploy.config import get_settings
from verideploy.database.factory import create_database_manager
from verideploy.rag.self_corrective.repository import PostgresSelfCorrectiveRunRepository
from verideploy.rag.self_corrective.service import SelfCorrectiveRAG


@lru_cache
def get_self_corrective_rag() -> SelfCorrectiveRAG:
    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        raise RuntimeError("self-corrective RAG runtime requires PostgreSQL/pgvector")
    db = create_database_manager(settings)
    return SelfCorrectiveRAG(
        pipeline=get_retrieval_pipeline(),
        repository=PostgresSelfCorrectiveRunRepository(db),
        external_search=None,
    )
