from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from verideploy.rag.embeddings.deterministic import DeterministicEmbeddingProvider
from verideploy.rag.embeddings.errors import EmbeddingDimensionDriftError, EmbeddingProviderError
from verideploy.rag.embeddings.openai_provider import OpenAIEmbeddingProvider
from verideploy.rag.embeddings.pipeline import EmbeddingPipeline
from verideploy.rag.embeddings.registry import EmbeddingModelRegistry
from verideploy.rag.embeddings.repository import SqlAlchemyEmbeddingRepository
from verideploy.rag.embeddings.schemas import (
    EmbeddingInput, EmbeddingModelSpec, EmbeddingProviderResult, EmbeddingRequest,
    EmbeddingState, EmbeddingUsage, EmbeddingVector,
)

MODEL = "text-embedding-test"
DIMS = 8


def repo():
    return SqlAlchemyEmbeddingRepository("sqlite+pysqlite:///:memory:", create_schema=True)


def registry():
    return EmbeddingModelRegistry([EmbeddingModelSpec(model=MODEL, dimensions=DIMS)])


@pytest.mark.asyncio
async def test_deterministic_provider_is_stable_and_normalized():
    provider = DeterministicEmbeddingProvider(default_dimensions=DIMS)
    one = await provider.embed(model=MODEL, inputs=["same text"], dimensions=DIMS)
    two = await provider.embed(model=MODEL, inputs=["same text"], dimensions=DIMS)
    assert one.vectors[0].values == two.vectors[0].values
    assert len(one.vectors[0].values) == DIMS


@pytest.mark.asyncio
async def test_pipeline_is_idempotent_and_uses_tenant_cache():
    provider = DeterministicEmbeddingProvider(default_dimensions=DIMS)
    pipeline = EmbeddingPipeline(provider=provider, registry=registry(), repository=repo(), default_model=MODEL)
    tenant = uuid4()
    request = EmbeddingRequest(tenant_id=tenant, correlation_id="corr-1", inputs=[EmbeddingInput(text="alpha")])
    first = await pipeline.embed(request)
    second = await pipeline.embed(request.model_copy(update={"request_id": uuid4()}))
    assert first.records[0].embedding_id == second.records[0].embedding_id
    assert second.cache_hits == 1
    assert second.provider_input_count == 0
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cache_never_crosses_tenants():
    provider = DeterministicEmbeddingProvider(default_dimensions=DIMS)
    pipeline = EmbeddingPipeline(provider=provider, registry=registry(), repository=repo(), default_model=MODEL)
    for tenant in (uuid4(), uuid4()):
        result = await pipeline.embed(EmbeddingRequest(tenant_id=tenant, correlation_id="corr", inputs=[EmbeddingInput(text="same")]))
        assert result.cache_hits == 0
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_pipeline_batches_async_and_preserves_input_order():
    provider = DeterministicEmbeddingProvider(default_dimensions=DIMS)
    pipeline = EmbeddingPipeline(provider=provider, registry=registry(), repository=repo(), default_model=MODEL, batch_size=2)
    result = await pipeline.embed(EmbeddingRequest(
        tenant_id=uuid4(), correlation_id="corr", inputs=[EmbeddingInput(text=f"item-{i}") for i in range(5)]
    ))
    assert len(result.records) == 5
    assert provider.calls == 3
    assert result.provider_input_count == 5


class WrongDimensionProvider:
    async def embed(self, *, model: str, inputs: list[str], dimensions: int | None = None):
        return EmbeddingProviderResult(model=model, vectors=[EmbeddingVector(index=i, values=[0.0] * (DIMS - 1)) for i, _ in enumerate(inputs)])


@pytest.mark.asyncio
async def test_provider_dimension_drift_fails_before_persistence():
    repository = repo()
    pipeline = EmbeddingPipeline(provider=WrongDimensionProvider(), registry=registry(), repository=repository, default_model=MODEL)
    tenant = uuid4()
    with pytest.raises(EmbeddingDimensionDriftError):
        await pipeline.embed(EmbeddingRequest(tenant_id=tenant, correlation_id="corr", inputs=[EmbeddingInput(text="alpha")]))
    assert repository.get_current(tenant_id=tenant, content_hash="0" * 64, model=MODEL, dimensions=DIMS) is None


def test_registry_refuses_silent_dimension_change():
    reg = registry()
    with pytest.raises(EmbeddingDimensionDriftError):
        reg.register(EmbeddingModelSpec(model=MODEL, dimensions=DIMS + 1, registry_version=2))
    with pytest.raises(EmbeddingDimensionDriftError):
        reg.resolve(MODEL, DIMS + 1)


class FlakyProvider:
    def __init__(self): self.calls = 0
    async def embed(self, *, model: str, inputs: list[str], dimensions: int | None = None):
        self.calls += 1
        if self.calls == 1:
            raise EmbeddingProviderError("temporary", retryable=True, retry_after_seconds=0)
        return EmbeddingProviderResult(
            model=model, vectors=[EmbeddingVector(index=i, values=[0.5] * DIMS) for i, _ in enumerate(inputs)],
            usage=EmbeddingUsage(prompt_tokens=7, total_tokens=7), provider_request_id="emb_req_1"
        )


@pytest.mark.asyncio
async def test_retryable_provider_failure_is_bounded_and_usage_tracked():
    provider = FlakyProvider()
    pipeline = EmbeddingPipeline(provider=provider, registry=registry(), repository=repo(), default_model=MODEL, max_attempts=2, sleep=lambda _: _instant())
    result = await pipeline.embed(EmbeddingRequest(tenant_id=uuid4(), correlation_id="corr", inputs=[EmbeddingInput(text="alpha")]))
    assert provider.calls == 2
    assert result.provider_prompt_tokens == 7
    assert result.provider_request_ids == ["emb_req_1"]
    assert pipeline.telemetry.events[-1].prompt_tokens == 7


async def _instant():
    return None


class FakeEmbeddings:
    def __init__(self): self.kwargs = None
    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            model=kwargs["model"], data=[SimpleNamespace(index=0, embedding=[0.1] * kwargs["dimensions"])],
            usage=SimpleNamespace(prompt_tokens=3, total_tokens=3), _request_id="req-openai-1"
        )


@pytest.mark.asyncio
async def test_openai_adapter_maps_batch_dimensions_and_float_encoding():
    embeddings = FakeEmbeddings()
    provider = OpenAIEmbeddingProvider(SimpleNamespace(embeddings=embeddings))
    result = await provider.embed(model=MODEL, inputs=["hello"], dimensions=DIMS)
    assert embeddings.kwargs == {"model": MODEL, "input": ["hello"], "encoding_format": "float", "dimensions": DIMS}
    assert result.provider_request_id == "req-openai-1"
    assert result.usage.prompt_tokens == 3


@pytest.mark.asyncio
async def test_reembedding_plan_marks_old_vectors_stale_and_state_is_explicit():
    repository = repo()
    provider = DeterministicEmbeddingProvider(default_dimensions=DIMS)
    reg = registry()
    reg.register(EmbeddingModelSpec(model="new-model", dimensions=12))
    pipeline = EmbeddingPipeline(provider=provider, registry=reg, repository=repository, default_model=MODEL)
    tenant = uuid4()
    result = await pipeline.embed(EmbeddingRequest(tenant_id=tenant, correlation_id="corr", inputs=[EmbeddingInput(text="alpha")]))
    plan = pipeline.plan_reembedding(tenant_id=tenant, from_model=MODEL, from_dimensions=DIMS, to_model="new-model", to_dimensions=12)
    assert plan.stale_records == 1
    assert repository.count_state(tenant_id=tenant, model=MODEL, dimensions=DIMS, state=EmbeddingState.STALE) == 1
    transitioning = pipeline.begin_reembedding(tenant_id=tenant, embedding_id=result.records[0].embedding_id)
    assert transitioning.state is EmbeddingState.REEMBEDDING
    failed = pipeline.fail_reembedding(tenant_id=tenant, embedding_id=result.records[0].embedding_id)
    assert failed.state is EmbeddingState.FAILED

@pytest.mark.asyncio
async def test_duplicate_content_in_same_batch_embeds_once_but_preserves_each_chunk_context():
    provider = DeterministicEmbeddingProvider(default_dimensions=DIMS)
    pipeline = EmbeddingPipeline(provider=provider, registry=registry(), repository=repo(), default_model=MODEL)
    chunk_a, chunk_b = uuid4(), uuid4()
    result = await pipeline.embed(EmbeddingRequest(
        tenant_id=uuid4(), correlation_id="corr", inputs=[
            EmbeddingInput(chunk_id=chunk_a, text="duplicate"),
            EmbeddingInput(chunk_id=chunk_b, text="duplicate"),
        ]
    ))
    assert result.provider_input_count == 1
    assert provider.calls == 1
    assert result.records[0].embedding_id == result.records[1].embedding_id
    assert result.records[0].chunk_id == chunk_a
    assert result.records[1].chunk_id == chunk_b
