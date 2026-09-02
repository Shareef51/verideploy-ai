from __future__ import annotations

from typing import Any

from verideploy.rag.embeddings.errors import EmbeddingProviderError
from verideploy.rag.embeddings.schemas import EmbeddingProviderResult, EmbeddingUsage, EmbeddingVector


class OpenAIEmbeddingProvider:
    """Thin official-SDK adapter. Retry ownership remains in EmbeddingPipeline."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def embed(self, *, model: str, inputs: list[str], dimensions: int | None = None) -> EmbeddingProviderResult:
        kwargs: dict[str, Any] = {"model": model, "input": inputs, "encoding_format": "float"}
        if dimensions is not None:
            kwargs["dimensions"] = dimensions
        try:
            response = await self._client.embeddings.create(**kwargs)
        except Exception as exc:
            raise self._classify(exc) from exc
        vectors = [
            EmbeddingVector(index=int(getattr(item, "index", index)), values=list(getattr(item, "embedding")))
            for index, item in enumerate(getattr(response, "data", []) or [])
        ]
        usage = getattr(response, "usage", None)
        return EmbeddingProviderResult(
            provider_request_id=getattr(response, "_request_id", None) or getattr(response, "request_id", None),
            model=str(getattr(response, "model", model)),
            vectors=vectors,
            usage=EmbeddingUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
            ),
        )

    @staticmethod
    def _classify(exc: Exception) -> EmbeddingProviderError:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__
        retryable = name in {"APIConnectionError", "APITimeoutError", "RateLimitError"} or status in {408, 409, 429} or (
            isinstance(status, int) and status >= 500
        )
        retry_after = None
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers:
            raw = headers.get("retry-after")
            try:
                retry_after = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                retry_after = None
        return EmbeddingProviderError("embedding provider request failed", retryable=retryable, retry_after_seconds=retry_after)
