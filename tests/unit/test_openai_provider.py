from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from verideploy.llm.contracts import AIRequest
from verideploy.llm.errors import AIErrorCode, AIProviderError
from verideploy.llm.openai_provider import OpenAIProvider


class FakeResponses:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, responses: FakeResponses):
        self.responses = responses


def request() -> AIRequest:
    return AIRequest(
        tenant_id=uuid4(), correlation_id="corr", operation="test", model="configured-model", input="hello"
    )


@pytest.mark.asyncio
async def test_openai_adapter_uses_responses_contract_and_request_metadata() -> None:
    response = SimpleNamespace(
        output_text="answer",
        _request_id="req_provider_123",
        usage=SimpleNamespace(input_tokens=3, output_tokens=4, total_tokens=7),
    )
    fake = FakeResponses(response=response)
    result = await OpenAIProvider(api_key="test-only", timeout_seconds=1, client=FakeClient(fake)).execute(request())
    assert result.output_text == "answer"
    assert result.provider_request_id == "req_provider_123"
    assert result.usage.total_tokens == 7
    assert fake.calls[0]["model"] == "configured-model"
    assert "verideploy_request_id" in fake.calls[0]["metadata"]


class FakeStatusError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.request_id = "req_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "code", "retryable"),
    [(401, AIErrorCode.AUTHENTICATION, False), (429, AIErrorCode.RATE_LIMITED, True), (500, AIErrorCode.PROVIDER_UNAVAILABLE, True)],
)
async def test_openai_error_classification(status_code, code, retryable) -> None:
    fake = FakeResponses(error=FakeStatusError(status_code))
    provider = OpenAIProvider(api_key="test-only", timeout_seconds=1, client=FakeClient(fake))
    with pytest.raises(AIProviderError) as exc_info:
        await provider.execute(request())
    assert exc_info.value.code == code
    assert exc_info.value.retryable is retryable
    assert exc_info.value.provider_request_id == "req_failed"
