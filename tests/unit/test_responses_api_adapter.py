from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from verideploy.llm.contracts import AIProviderName, AIRequest, AIResult, AIUsage
from verideploy.llm.controls import InMemoryRequestController, LocalControlPolicy
from verideploy.llm.errors import AIErrorCode, AIProviderError
from verideploy.llm.gateway import AIGateway
from verideploy.llm.openai_provider import OpenAIProvider
from verideploy.llm.persistence import InMemoryResponsePersistence, SqlAlchemyResponsePersistence
from verideploy.llm.responses import (
    AIFunctionCallOutput,
    AIFunctionToolChoice,
    AIMessageInput,
    AIResponseStatus,
    AIStreamEvent,
    AIStreamEventType,
    AIToolDefinition,
)


def req() -> AIRequest:
    return AIRequest(
        tenant_id=uuid4(),
        correlation_id="corr",
        operation="standard_rag",
        model="configured-model",
        input="Find the deployment owner",
        instructions="Use tools only when needed.",
        max_output_tokens=256,
        tools=[
            AIToolDefinition(
                name="lookup_service_owner",
                description="Look up a service owner",
                parameters={
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                    "additionalProperties": False,
                },
            )
        ],
        tool_choice=AIFunctionToolChoice(name="lookup_service_owner"),
        previous_response_id="resp_previous",
        store_provider_response=True,
        metadata={"workflow": "responses-api-adapter"},
    )


class FakeAsyncStream:
    def __init__(self, events):
        self.events = list(events)

    def __aiter__(self):
        self._iter = iter(self.events)
        return self

    async def __anext__(self):
        try:
            value = next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc
        if isinstance(value, Exception):
            raise value
        return value


class FakeResponses:
    def __init__(self, *, response=None, stream_events=None, cancel_response=None):
        self.response = response
        self.stream_events = stream_events or []
        self.cancel_response = cancel_response or SimpleNamespace(status="cancelled")
        self.calls: list[dict] = []
        self.cancel_calls: list[str] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return FakeAsyncStream(self.stream_events)
        return self.response

    async def cancel(self, response_id: str):
        self.cancel_calls.append(response_id)
        return self.cancel_response


class FakeClient:
    def __init__(self, responses: FakeResponses):
        self.responses = responses


def provider_response(status: str = "completed"):
    return SimpleNamespace(
        id="resp_123",
        status=status,
        output_text="The owner is Platform Engineering.",
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call_owner_1",
                name="lookup_service_owner",
                arguments='{"service":"payment-service"}',
            )
        ],
        _request_id="req_openai_123",
        usage=SimpleNamespace(
            input_tokens=20,
            output_tokens=10,
            total_tokens=30,
            input_tokens_details=SimpleNamespace(cached_tokens=5),
            output_tokens_details=SimpleNamespace(reasoning_tokens=2),
        ),
        incomplete_details=(SimpleNamespace(reason="max_output_tokens") if status == "incomplete" else None),
    )


@pytest.mark.asyncio
async def test_nonstreaming_maps_full_responses_request_and_result_contract() -> None:
    fake = FakeResponses(response=provider_response())
    result = await OpenAIProvider(api_key="test-only", timeout_seconds=1, client=FakeClient(fake)).execute(req())

    call = fake.calls[0]
    assert call["model"] == "configured-model"
    assert call["stream"] is False
    assert call["instructions"] == "Use tools only when needed."
    assert call["previous_response_id"] == "resp_previous"
    assert call["store"] is True
    assert call["tools"][0]["name"] == "lookup_service_owner"
    assert call["tool_choice"] == {"type": "function", "name": "lookup_service_owner"}
    assert result.provider_response_id == "resp_123"
    assert result.provider_request_id == "req_openai_123"
    assert result.response_status is AIResponseStatus.COMPLETED
    assert result.tool_calls[0].call_id == "call_owner_1"
    assert result.usage.cached_input_tokens == 5
    assert result.usage.reasoning_tokens == 2


@pytest.mark.asyncio
async def test_streaming_and_nonstreaming_finish_with_same_typed_result_contract() -> None:
    final = provider_response()
    fake = FakeResponses(
        response=final,
        stream_events=[
            SimpleNamespace(type="response.created", response=SimpleNamespace(id="resp_123")),
            SimpleNamespace(type="response.output_text.delta", delta="The owner is "),
            SimpleNamespace(type="response.output_text.delta", delta="Platform Engineering."),
            SimpleNamespace(type="response.completed", response=final),
        ],
    )
    provider = OpenAIProvider(api_key="test-only", timeout_seconds=1, client=FakeClient(fake))
    request = req()
    direct = await provider.execute(request)
    events = [event async for event in provider.stream(request)]
    streamed = events[-1].final_result

    assert isinstance(streamed, AIResult)
    assert streamed.model_dump(exclude={"latency_ms"}) == direct.model_dump(exclude={"latency_ms"})
    assert [e.type for e in events] == [
        AIStreamEventType.RESPONSE_CREATED,
        AIStreamEventType.OUTPUT_TEXT_DELTA,
        AIStreamEventType.OUTPUT_TEXT_DELTA,
        AIStreamEventType.RESPONSE_COMPLETED,
    ]


@pytest.mark.asyncio
async def test_incomplete_response_preserves_reason_and_terminal_type() -> None:
    final = provider_response("incomplete")
    fake = FakeResponses(stream_events=[SimpleNamespace(type="response.incomplete", response=final)])
    provider = OpenAIProvider(api_key="test-only", timeout_seconds=1, client=FakeClient(fake))
    events = [event async for event in provider.stream(req())]
    result = events[-1].final_result
    assert events[-1].type is AIStreamEventType.RESPONSE_INCOMPLETE
    assert result.response_status is AIResponseStatus.INCOMPLETE
    assert result.metadata["incomplete_reason"] == "max_output_tokens"


@pytest.mark.asyncio
async def test_cancel_calls_responses_cancel_endpoint() -> None:
    fake = FakeResponses()
    provider = OpenAIProvider(api_key="test-only", timeout_seconds=1, client=FakeClient(fake))
    assert await provider.cancel("resp_background_1") is True
    assert fake.cancel_calls == ["resp_background_1"]


@pytest.mark.asyncio
async def test_gateway_persists_normalized_response_snapshot() -> None:
    persistence = InMemoryResponsePersistence()
    fake = FakeResponses(response=provider_response())
    provider = OpenAIProvider(api_key="test-only", timeout_seconds=1, client=FakeClient(fake))
    request = req()
    result = await AIGateway(
        provider=provider,
        controller=InMemoryRequestController(LocalControlPolicy(100, Decimal("10"))),
        response_persistence=persistence,
        max_attempts=1,
    ).execute(request)
    stored = await persistence.get(tenant_id=request.tenant_id, provider_response_id=result.provider_response_id or "")
    assert stored is not None
    assert stored.provider_response_id == result.provider_response_id
    assert stored.tool_calls == result.tool_calls


@pytest.mark.asyncio
async def test_sqlalchemy_response_persistence_is_tenant_scoped(tmp_path) -> None:
    db = SqlAlchemyResponsePersistence(f"sqlite+pysqlite:///{tmp_path / 'responses.db'}", create_schema=True)
    request = req()
    result = AIResult(
        request_id=request.request_id,
        provider=AIProviderName.OPENAI,
        model="configured-model",
        output_text="persisted",
        provider_response_id="resp_durable_1",
        usage=AIUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        latency_ms=1,
        attempts=1,
    )
    await db.save(tenant_id=request.tenant_id, request=request, result=result)
    assert await db.get(tenant_id=request.tenant_id, provider_response_id="resp_durable_1") is not None
    assert await db.get(tenant_id=uuid4(), provider_response_id="resp_durable_1") is None


class PreVisibleFailureProvider:
    name = "test"

    def __init__(self):
        self.calls = 0

    async def execute(self, request: AIRequest) -> AIResult:
        raise AssertionError("execute not used")

    async def stream(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]:
        self.calls += 1
        if self.calls == 1:
            raise AIProviderError("temporary", code=AIErrorCode.CONNECTION, retryable=True, provider="test")
        result = AIResult(
            request_id=request.request_id,
            provider=AIProviderName.TEST,
            model=request.model or "",
            output_text="recovered",
            provider_response_id="resp_retry",
            usage=AIUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            latency_ms=1,
            attempts=1,
        )
        yield AIStreamEvent(
            type=AIStreamEventType.RESPONSE_COMPLETED,
            sequence_number=1,
            request_id=str(request.request_id),
            provider_response_id="resp_retry",
            final_result=result,
        )

    async def cancel(self, response_id: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_gateway_retries_stream_only_before_visible_output() -> None:
    provider = PreVisibleFailureProvider()
    gateway = AIGateway(
        provider=provider,
        controller=InMemoryRequestController(LocalControlPolicy(100, Decimal("10"))),
        max_attempts=2,
        base_backoff_seconds=0,
    )
    events = [event async for event in gateway.stream(req())]
    assert provider.calls == 2
    assert events[-1].final_result.output_text == "recovered"
    assert events[-1].final_result.attempts == 2


class PostVisibleFailureProvider(PreVisibleFailureProvider):
    async def stream(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]:
        self.calls += 1
        yield AIStreamEvent(
            type=AIStreamEventType.OUTPUT_TEXT_DELTA,
            sequence_number=1,
            request_id=str(request.request_id),
            delta="partial",
        )
        raise AIProviderError("stream broke", code=AIErrorCode.CONNECTION, retryable=True, provider="test")


@pytest.mark.asyncio
async def test_gateway_never_retries_after_visible_stream_output() -> None:
    provider = PostVisibleFailureProvider()
    gateway = AIGateway(
        provider=provider,
        controller=InMemoryRequestController(LocalControlPolicy(100, Decimal("10"))),
        max_attempts=3,
        base_backoff_seconds=0,
    )
    received = []
    with pytest.raises(AIProviderError):
        async for event in gateway.stream(req()):
            received.append(event)
    assert provider.calls == 1
    assert received[0].delta == "partial"


@pytest.mark.asyncio
async def test_typed_message_and_function_output_inputs_are_forwarded() -> None:
    fake = FakeResponses(response=provider_response())
    provider = OpenAIProvider(api_key="test-only", timeout_seconds=1, client=FakeClient(fake))
    request = req().model_copy(
        update={
            "input": [
                AIMessageInput(role="user", content="Who owns payment-service?"),
                AIFunctionCallOutput(call_id="call_owner_1", output='{"owner":"platform"}'),
            ]
        }
    )
    await provider.execute(request)
    assert fake.calls[0]["input"] == [
        {"type": "message", "role": "user", "content": "Who owns payment-service?"},
        {"type": "function_call_output", "call_id": "call_owner_1", "output": '{"owner":"platform"}'},
    ]
