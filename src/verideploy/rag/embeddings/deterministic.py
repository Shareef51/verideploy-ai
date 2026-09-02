from __future__ import annotations

import hashlib
import math
from uuid import uuid4

from verideploy.rag.embeddings.schemas import EmbeddingProviderResult, EmbeddingUsage, EmbeddingVector


class DeterministicEmbeddingProvider:
    """Stable, network-free provider for CI/demo verification using the production contract."""

    def __init__(self, *, default_dimensions: int = 64) -> None:
        self.default_dimensions = default_dimensions
        self.calls = 0

    async def embed(self, *, model: str, inputs: list[str], dimensions: int | None = None) -> EmbeddingProviderResult:
        self.calls += 1
        dims = dimensions or self.default_dimensions
        vectors: list[EmbeddingVector] = []
        for index, text in enumerate(inputs):
            seed = hashlib.sha256(f"{model}\0{text}".encode("utf-8")).digest()
            raw = []
            for offset in range(dims):
                byte = seed[offset % len(seed)]
                raw.append((byte / 127.5) - 1.0)
            norm = math.sqrt(sum(value * value for value in raw)) or 1.0
            vectors.append(EmbeddingVector(index=index, values=[value / norm for value in raw]))
        estimated_tokens = sum(max(1, len(text) // 4) for text in inputs)
        return EmbeddingProviderResult(
            provider_request_id=f"det-{uuid4()}",
            model=model,
            vectors=vectors,
            usage=EmbeddingUsage(prompt_tokens=estimated_tokens, total_tokens=estimated_tokens),
        )
