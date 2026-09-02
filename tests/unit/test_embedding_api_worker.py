from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from services.ai.embedding_pipeline import get_embedding_pipeline
from services.ai.main import app
from verideploy.rag.embeddings.deterministic import DeterministicEmbeddingProvider
from verideploy.rag.embeddings.pipeline import EmbeddingPipeline
from verideploy.rag.embeddings.registry import EmbeddingModelRegistry
from verideploy.rag.embeddings.repository import SqlAlchemyEmbeddingRepository
from verideploy.rag.embeddings.schemas import EmbeddingInput, EmbeddingModelSpec, EmbeddingRequest
from workers.embedding.embedding_worker import EmbeddingWorker


def pipeline():
    return EmbeddingPipeline(
        provider=DeterministicEmbeddingProvider(default_dimensions=8),
        registry=EmbeddingModelRegistry([EmbeddingModelSpec(model="embed-test", dimensions=8)]),
        repository=SqlAlchemyEmbeddingRepository("sqlite+pysqlite:///:memory:", create_schema=True),
        default_model="embed-test",
    )


def test_private_embedding_endpoint_requires_service_identity_and_tenant_scope():
    app.dependency_overrides[get_embedding_pipeline] = pipeline
    client = TestClient(app)
    tenant = uuid4()
    payload = EmbeddingRequest(tenant_id=tenant, correlation_id="corr", inputs=[EmbeddingInput(text="hello")]).model_dump(mode="json")
    assert client.post("/internal/v1/embeddings", json=payload).status_code == 401
    assert client.post(
        "/internal/v1/embeddings", json=payload,
        headers={"x-internal-service": "verideploy-gateway", "x-tenant-id": str(uuid4())},
    ).status_code == 403
    response = client.post(
        "/internal/v1/embeddings", json=payload,
        headers={"x-internal-service": "verideploy-gateway", "x-tenant-id": str(tenant)},
    )
    assert response.status_code == 200
    assert response.json()["dimensions"] == 8
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_embedding_worker_uses_same_pipeline_contract():
    worker = EmbeddingWorker(pipeline())
    request = EmbeddingRequest(tenant_id=uuid4(), correlation_id="worker-corr", inputs=[EmbeddingInput(text="worker text")])
    result = await worker.handle(request.model_dump_json())
    assert result.provider_input_count == 1
    assert result.dimensions == 8
