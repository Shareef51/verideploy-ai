from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Protocol, Sequence
from uuid import UUID


@dataclass(frozen=True)
class SemanticRerankDocument:
    chunk_id: UUID
    title: str
    content: str


class SemanticReranker(Protocol):
    """Cross-encoder/provider boundary; scores must be normalized to [0, 1]."""

    async def rerank(self, *, tenant_id: UUID, correlation_id: str, query: str, documents: Sequence[SemanticRerankDocument], model: str, dimensions: int) -> dict[UUID, float]: ...


class EmbeddingSemanticReranker:
    """Semantic bi-encoder reranker backed by the production embedding pipeline."""

    def __init__(self, embeddings) -> None:
        self.embeddings = embeddings

    async def rerank(self, *, tenant_id: UUID, correlation_id: str, query: str, documents: Sequence[SemanticRerankDocument], model: str, dimensions: int) -> dict[UUID, float]:
        from verideploy.rag.embeddings.schemas import EmbeddingInput, EmbeddingRequest
        batch = await self.embeddings.embed(EmbeddingRequest(tenant_id=tenant_id, correlation_id=correlation_id, model=model, dimensions=dimensions, inputs=[EmbeddingInput(text=query), *[EmbeddingInput(chunk_id=d.chunk_id, text=f"{d.title}\n{d.content}") for d in documents]]))
        query_vector = batch.records[0].values
        def cosine(values: list[float]) -> float:
            denominator = sqrt(sum(x*x for x in query_vector)) * sqrt(sum(x*x for x in values))
            raw = sum(a*b for a, b in zip(query_vector, values, strict=True)) / denominator if denominator else 0.0
            return min(1.0, max(0.0, (raw + 1.0) / 2.0))
        return {document.chunk_id: cosine(record.values) for document, record in zip(documents, batch.records[1:], strict=True)}
