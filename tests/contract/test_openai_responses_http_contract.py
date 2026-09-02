from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from verideploy.llm.contracts import AIRequest
from verideploy.llm.openai_provider import OpenAIProvider
from verideploy.llm.responses import AIToolDefinition


class HTTPBackedResponses:
    """Mock HTTP façade used only to verify the SDK-facing adapter contract at /v1/responses."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def create(self, **kwargs):
        response = await self.client.post("/v1/responses", json=kwargs)
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        return SimpleNamespace(
            id=body.get("id"),
            status=body.get("status"),
            output_text=body.get("output_text", ""),
            output=[],
            request_id=response.headers.get("x-request-id"),
            usage=SimpleNamespace(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                input_tokens_details=None,
                output_tokens_details=None,
            ),
            incomplete_details=None,
        )

    async def cancel(self, response_id: str):
        response = await self.client.post(f"/v1/responses/{response_id}/cancel")
        response.raise_for_status()
        return SimpleNamespace(**response.json())


class FakeClient:
    def __init__(self, responses):
        self.responses = responses


@pytest.mark.asyncio
async def test_responses_adapter_matches_mocked_http_contract() -> None:
    captured: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(
            200,
            headers={"x-request-id": "req_http_contract"},
            json={
                "id": "resp_http_contract",
                "status": "completed",
                "output_text": "contract-ok",
                "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.openai.com") as http_client:
        provider = OpenAIProvider(
            api_key="test-only",
            timeout_seconds=1,
            client=FakeClient(HTTPBackedResponses(http_client)),
        )
        request = AIRequest(
            tenant_id=uuid4(),
            correlation_id="corr-http-contract",
            operation="standard_rag",
            model="configured-model",
            input="Check this contract",
            instructions="Answer concisely.",
            tools=[AIToolDefinition(name="lookup", parameters={"type": "object", "properties": {}})],
            store_provider_response=True,
        )
        result = await provider.execute(request)

    assert captured[0]["model"] == "configured-model"
    assert captured[0]["stream"] is False
    assert captured[0]["store"] is True
    assert captured[0]["tools"][0]["type"] == "function"
    assert captured[0]["metadata"]["verideploy_request_id"] == str(request.request_id)
    assert result.provider_response_id == "resp_http_contract"
    assert result.provider_request_id == "req_http_contract"
    assert result.output_text == "contract-ok"
    assert result.usage.total_tokens == 16
