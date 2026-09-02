from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from verideploy.knowledge.corpus import EngineeringKnowledgeCorpus
from verideploy.rag.embeddings.pipeline import EmbeddingPipeline
from verideploy.rag.embeddings.schemas import EmbeddingInput, EmbeddingRequest
from verideploy.rag.retrieval.corpus import RetrievalChunkInput, RetrievalDocumentInput


class RetrievalCorpusWriter(Protocol):
    def upsert_document(self, item: RetrievalDocumentInput) -> None: ...
    def upsert_chunk(self, item: RetrievalChunkInput) -> str: ...


@dataclass(frozen=True)
class KnowledgeIngestionResult:
    documents_upserted: int
    chunks_upserted: int
    embeddings_requested: int
    corpus_version: str
    manifest_sha256: str


class KnowledgeCorpusIngestor:
    """Idempotently materialize a validated Engineering Knowledge Base corpus into the existing retrieval stack."""

    def __init__(
        self,
        *,
        corpus: EngineeringKnowledgeCorpus,
        writer: RetrievalCorpusWriter,
        embedding_pipeline: EmbeddingPipeline | None = None,
        retrieval_cache=None,
    ) -> None:
        self.corpus = corpus
        self.writer = writer
        self.embedding_pipeline = embedding_pipeline
        self.retrieval_cache = retrieval_cache

    async def ingest(self, *, correlation_id: str = "knowledge-ingestion") -> KnowledgeIngestionResult:
        document_count = 0
        chunk_count = 0
        embedding_inputs: list[EmbeddingInput] = []

        for document, chunks in self.corpus.retrieval_inputs():
            self.writer.upsert_document(document)
            document_count += 1
            for chunk in chunks:
                self.writer.upsert_chunk(chunk)
                chunk_count += 1
                embedding_inputs.append(
                    EmbeddingInput(document_id=chunk.document_id, chunk_id=chunk.chunk_id, text=chunk.content)
                )

        if self.embedding_pipeline is not None and embedding_inputs:
            await self.embedding_pipeline.embed(
                EmbeddingRequest(
                    tenant_id=self.corpus.manifest.tenant_id,
                    correlation_id=correlation_id,
                    inputs=embedding_inputs,
                )
            )
        if self.retrieval_cache is not None:
            invalidated=self.retrieval_cache.invalidate_tenant(self.corpus.manifest.tenant_id)
            import inspect
            if inspect.isawaitable(invalidated): await invalidated

        return KnowledgeIngestionResult(
            documents_upserted=document_count,
            chunks_upserted=chunk_count,
            embeddings_requested=len(embedding_inputs) if self.embedding_pipeline is not None else 0,
            corpus_version=self.corpus.manifest.corpus_version,
            manifest_sha256=self.corpus.manifest_digest(),
        )
