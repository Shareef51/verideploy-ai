from __future__ import annotations

import json

from verideploy.rag.embeddings.pipeline import EmbeddingPipeline
from verideploy.rag.embeddings.schemas import EmbeddingBatchResult, EmbeddingRequest


class EmbeddingWorker:
    """Transport-independent handler used by Kafka/runtime adapters."""

    def __init__(self, pipeline: EmbeddingPipeline) -> None:
        self._pipeline = pipeline

    async def handle(self, payload: bytes | str | dict[str, object]) -> EmbeddingBatchResult:
        if isinstance(payload, bytes):
            raw = json.loads(payload.decode("utf-8"))
        elif isinstance(payload, str):
            raw = json.loads(payload)
        else:
            raw = payload
        request = EmbeddingRequest.model_validate(raw)
        return await self._pipeline.embed(request)
