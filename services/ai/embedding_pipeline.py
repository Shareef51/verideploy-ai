from __future__ import annotations

from functools import lru_cache

from verideploy.config import get_settings
from verideploy.rag.embeddings.factory import build_embedding_pipeline
from verideploy.database.session import DatabaseManager
from verideploy.database.factory import create_database_manager
from verideploy.database.vector_config import load_vector_index_config, validate_embedding_settings
from verideploy.rag.embeddings.pgvector_repository import PgVectorEmbeddingCacheRepository
from verideploy.rag.embeddings.repository import SqlAlchemyEmbeddingRepository


@lru_cache
def get_embedding_pipeline():
    settings = get_settings()
    if settings.app_env == "test" or settings.database_url.startswith("sqlite"):
        repository = SqlAlchemyEmbeddingRepository(settings.database_url, create_schema=True)
    else:
        vector_config = load_vector_index_config(settings.vector_index_config_path)
        validate_embedding_settings(
            config=vector_config, model=settings.openai_embedding_model, dimensions=settings.openai_embedding_dimensions
        )
        repository = PgVectorEmbeddingCacheRepository(
            create_database_manager(settings),
            model_name=settings.openai_embedding_model, dimensions=settings.openai_embedding_dimensions,
        )
    if settings.ai_provider == "test":
        return build_embedding_pipeline(settings, repository=repository, deterministic=True)

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("official OpenAI SDK is required for production embeddings") from exc

    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    client = AsyncOpenAI(api_key=api_key, timeout=settings.ai_timeout_seconds, max_retries=0)
    return build_embedding_pipeline(settings, repository=repository, openai_client=client)
