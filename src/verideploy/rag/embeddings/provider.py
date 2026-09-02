from __future__ import annotations

from typing import Protocol

from verideploy.rag.embeddings.schemas import EmbeddingProviderResult


class EmbeddingProvider(Protocol):
    async def embed(self, *, model: str, inputs: list[str], dimensions: int | None = None) -> EmbeddingProviderResult: ...
