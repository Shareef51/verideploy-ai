from __future__ import annotations

from typing import Any

from verideploy.config import Settings
from verideploy.rag.embeddings.deterministic import DeterministicEmbeddingProvider
from verideploy.rag.embeddings.openai_provider import OpenAIEmbeddingProvider
from verideploy.rag.embeddings.pipeline import EmbeddingPipeline
from verideploy.rag.embeddings.registry import EmbeddingModelRegistry
from verideploy.rag.embeddings.repository import EmbeddingRepository
from verideploy.rag.embeddings.schemas import EmbeddingModelSpec


def build_embedding_registry(settings: Settings) -> EmbeddingModelRegistry:
    return EmbeddingModelRegistry([
        EmbeddingModelSpec(
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
            provider="openai",
            registry_version=1,
            supports_dimensions_override=True,
        )
    ])


def build_embedding_pipeline(
    settings: Settings,
    *,
    repository: EmbeddingRepository,
    openai_client: Any | None = None,
    deterministic: bool = False,
) -> EmbeddingPipeline:
    registry = build_embedding_registry(settings)
    if deterministic:
        provider = DeterministicEmbeddingProvider(default_dimensions=settings.openai_embedding_dimensions)
    else:
        if openai_client is None:
            raise ValueError("openai_client is required for the production embedding provider")
        provider = OpenAIEmbeddingProvider(openai_client)
    return EmbeddingPipeline(
        provider=provider,
        registry=registry,
        repository=repository,
        default_model=settings.openai_embedding_model,
        batch_size=settings.embedding_batch_size,
        max_attempts=settings.embedding_max_attempts,
        max_concurrency=settings.embedding_max_concurrency,
    )
