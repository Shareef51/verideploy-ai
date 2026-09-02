from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from services.ai.ai_gateway import get_ai_gateway
from services.ai.main import app
from verideploy.llm.contracts import AIRequest
from verideploy.llm.controls import InMemoryRequestController, LocalControlPolicy
from verideploy.llm.gateway import AIGateway
from verideploy.llm.persistence import InMemoryResponsePersistence
from verideploy.llm.test_provider import DeterministicTestProvider


def gateway() -> AIGateway:
    return AIGateway(
        provider=DeterministicTestProvider(output_text="private-ok"),
        controller=InMemoryRequestController(LocalControlPolicy(100, Decimal("10"))),
        response_persistence=InMemoryResponsePersistence(),
        max_attempts=1,
    )


def payload(tenant_id):
    return AIRequest(
        tenant_id=tenant_id,
        correlation_id="corr-private",
        operation="test",
        model="test-model",
        input="hello",
    ).model_dump(mode="json")


def test_private_responses_endpoint_requires_service_identity() -> None:
    tenant = uuid4()
    app.dependency_overrides[get_ai_gateway] = gateway
    try:
        client = TestClient(app)
        response = client.post("/internal/v1/ai/responses", json=payload(tenant))
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_private_responses_endpoint_executes_and_persists() -> None:
    tenant = uuid4()
    instance = gateway()
    app.dependency_overrides[get_ai_gateway] = lambda: instance
    try:
        client = TestClient(app)
        headers = {"x-internal-service": "verideploy-gateway", "x-tenant-id": str(tenant)}
        response = client.post("/internal/v1/ai/responses", json=payload(tenant), headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["output_text"] == "private-ok"
        response_id = body["provider_response_id"]
        fetched = client.get(f"/internal/v1/ai/responses/{response_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["request_id"] == body["request_id"]
    finally:
        app.dependency_overrides.clear()
