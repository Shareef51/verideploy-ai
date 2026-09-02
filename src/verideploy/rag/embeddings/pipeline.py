from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass

from verideploy.rag.embeddings.errors import EmbeddingDimensionDriftError, EmbeddingProviderError
from verideploy.rag.embeddings.provider import EmbeddingProvider
from verideploy.rag.embeddings.registry import EmbeddingModelRegistry
from verideploy.rag.embeddings.repository import EmbeddingRepository
from verideploy.rag.embeddings.schemas import (
    EmbeddingBatchResult, EmbeddingRecord, EmbeddingRequest, EmbeddingState, ReembeddingPlan,
)


@dataclass(frozen=True)
class EmbeddingTelemetryEvent:
    tenant_id: str
    request_id: str
    model: str
    dimensions: int
    batch_size: int
    cache_hits: int
    provider_inputs: int
    prompt_tokens: int | None
    provider_request_ids: tuple[str, ...]


class EmbeddingTelemetry:
    def __init__(self) -> None:
        self.events: list[EmbeddingTelemetryEvent] = []

    def emit(self, event: EmbeddingTelemetryEvent) -> None:
        self.events.append(event)


class EmbeddingPipeline:
    def __init__(
        self, *, provider: EmbeddingProvider, registry: EmbeddingModelRegistry,
        repository: EmbeddingRepository, default_model: str, batch_size: int = 128,
        max_attempts: int = 3, max_concurrency: int = 4, telemetry: EmbeddingTelemetry | None = None,
        sleep: Callable[[float], asyncio.Future] | None = None,
    ) -> None:
        if not 1 <= batch_size <= 2048:
            raise ValueError("batch_size must be between 1 and 2048")
        if not 1 <= max_attempts <= 8:
            raise ValueError("max_attempts must be between 1 and 8")
        self._provider = provider; self._registry = registry; self._repository = repository
        self._default_model = default_model; self._batch_size = batch_size; self._max_attempts = max_attempts
        self._semaphore = asyncio.Semaphore(max_concurrency); self._telemetry = telemetry or EmbeddingTelemetry()
        self._sleep = sleep or asyncio.sleep

    @property
    def telemetry(self) -> EmbeddingTelemetry:
        return self._telemetry

    async def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        model = request.model or self._default_model
        spec = self._registry.resolve(model, request.dimensions)
        dimensions = spec.dimensions
        records_by_index: dict[int, EmbeddingRecord] = {}
        pending_unique: list[tuple[str, str]] = []
        pending_indices: dict[str, list[int]] = {}
        cache_hits = 0

        for index, item in enumerate(request.inputs):
            content_hash = hashlib.sha256(item.text.encode("utf-8")).hexdigest()
            cached = self._repository.get_current(
                tenant_id=request.tenant_id, content_hash=content_hash, model=model, dimensions=dimensions
            )
            if cached is not None:
                records_by_index[index] = cached.model_copy(
                    update={"document_id": item.document_id, "chunk_id": item.chunk_id}
                )
                cache_hits += 1
                continue
            if content_hash not in pending_indices:
                pending_unique.append((content_hash, item.text))
                pending_indices[content_hash] = []
            pending_indices[content_hash].append(index)

        provider_ids: list[str] = []
        prompt_tokens = 0
        saw_usage = False
        chunks = [pending_unique[i:i + self._batch_size] for i in range(0, len(pending_unique), self._batch_size)]
        results = await asyncio.gather(*(self._embed_chunk(model, dimensions, chunk) for chunk in chunks)) if chunks else []
        for chunk, provider_result in zip(chunks, results, strict=True):
            if len(provider_result.vectors) != len(chunk):
                raise EmbeddingDimensionDriftError("embedding provider returned unexpected vector count")
            if provider_result.provider_request_id:
                provider_ids.append(provider_result.provider_request_id)
            if provider_result.usage.prompt_tokens is not None:
                prompt_tokens += provider_result.usage.prompt_tokens
                saw_usage = True
            by_provider_index = {vector.index: vector for vector in provider_result.vectors}
            for local_index, (content_hash, _) in enumerate(chunk):
                vector = by_provider_index.get(local_index)
                if vector is None:
                    raise EmbeddingDimensionDriftError(f"embedding provider omitted vector index {local_index}")
                if len(vector.values) != dimensions:
                    raise EmbeddingDimensionDriftError(
                        f"embedding dimension drift: registry={dimensions}, provider={len(vector.values)}, model={model}"
                    )
                stored = self._repository.save(EmbeddingRecord(
                    tenant_id=request.tenant_id, content_hash=content_hash, model=model, dimensions=dimensions,
                    registry_version=spec.registry_version, values=vector.values,
                    provider_request_id=provider_result.provider_request_id, prompt_tokens=None,
                ))
                for original_index in pending_indices[content_hash]:
                    item = request.inputs[original_index]
                    records_by_index[original_index] = stored.model_copy(
                        update={"document_id": item.document_id, "chunk_id": item.chunk_id}
                    )

        records = [records_by_index[index] for index in range(len(request.inputs))]
        self._telemetry.emit(EmbeddingTelemetryEvent(
            tenant_id=str(request.tenant_id), request_id=str(request.request_id), model=model, dimensions=dimensions,
            batch_size=len(request.inputs), cache_hits=cache_hits, provider_inputs=len(pending_unique),
            prompt_tokens=prompt_tokens if saw_usage else None, provider_request_ids=tuple(provider_ids),
        ))
        return EmbeddingBatchResult(
            request_id=request.request_id, tenant_id=request.tenant_id, model=model, dimensions=dimensions,
            records=records, cache_hits=cache_hits, provider_input_count=len(pending_unique),
            provider_prompt_tokens=prompt_tokens if saw_usage else None, provider_request_ids=provider_ids,
        )

    async def _embed_chunk(self, model: str, dimensions: int, chunk: list[tuple[str, str]]):
        async with self._semaphore:
            last: EmbeddingProviderError | None = None
            for attempt in range(1, self._max_attempts + 1):
                try:
                    return await self._provider.embed(model=model, inputs=[text for _, text in chunk], dimensions=dimensions)
                except EmbeddingProviderError as exc:
                    last = exc
                    if not exc.retryable or attempt >= self._max_attempts:
                        raise
                    delay = exc.retry_after_seconds if exc.retry_after_seconds is not None else min(4.0, 0.25 * (2 ** (attempt - 1)))
                    await self._sleep(delay + random.uniform(0, min(0.1, delay / 4)))
            assert last is not None
            raise last

    def plan_reembedding(self, *, tenant_id, from_model: str, from_dimensions: int, to_model: str, to_dimensions: int) -> ReembeddingPlan:
        self._registry.resolve(to_model, to_dimensions)
        stale = self._repository.mark_stale_for_migration(
            tenant_id=tenant_id, model=from_model, dimensions=from_dimensions
        )
        return ReembeddingPlan(
            tenant_id=tenant_id, from_model=from_model, from_dimensions=from_dimensions,
            to_model=to_model, to_dimensions=to_dimensions, stale_records=stale,
        )

    def begin_reembedding(self, *, tenant_id, embedding_id):
        return self._repository.transition_state(tenant_id=tenant_id, embedding_id=embedding_id, state=EmbeddingState.REEMBEDDING)

    def fail_reembedding(self, *, tenant_id, embedding_id):
        return self._repository.transition_state(tenant_id=tenant_id, embedding_id=embedding_id, state=EmbeddingState.FAILED)
