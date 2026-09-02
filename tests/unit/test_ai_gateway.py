from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from verideploy.llm.contracts import AIRequest
from verideploy.llm.controls import InMemoryRequestController, LocalControlPolicy
from verideploy.llm.errors import AIErrorCode, AIProviderError
from verideploy.llm.gateway import AIGateway
from verideploy.llm.test_provider import DeterministicTestProvider


def request() -> AIRequest:
    return AIRequest(
        tenant_id=uuid4(),
        correlation_id="corr",
        operation=".test",
        model="test-model",
        input="synthetic authorized input",
    )


def controller(rpm: int = 10, budget: str = "10") -> InMemoryRequestController:
    return InMemoryRequestController(LocalControlPolicy(requests_per_minute=rpm, monthly_budget_usd=Decimal(budget)))


@pytest.mark.asyncio
async def test_success_is_typed_and_tracks_attempts() -> None:
    provider = DeterministicTestProvider(output_text="ok")
    result = await AIGateway(provider=provider, controller=controller()).execute(request())
    assert result.output_text == "ok"
    assert result.attempts == 1
    assert result.provider.value == "test"


@pytest.mark.asyncio
async def test_retryable_provider_failure_retries_then_succeeds() -> None:
    failure = AIProviderError("temporary", code=AIErrorCode.RATE_LIMITED, retryable=True, provider="test")
    provider = DeterministicTestProvider(failures=[failure])
    gateway = AIGateway(provider=provider, controller=controller(), max_attempts=3, base_backoff_seconds=0)
    result = await gateway.execute(request())
    assert result.attempts == 2
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_non_retryable_failure_is_not_retried() -> None:
    failure = AIProviderError("bad", code=AIErrorCode.INVALID_REQUEST, retryable=False, provider="test")
    provider = DeterministicTestProvider(failures=[failure])
    with pytest.raises(AIProviderError) as exc_info:
        await AIGateway(provider=provider, controller=controller(), max_attempts=3).execute(request())
    assert exc_info.value.code == AIErrorCode.INVALID_REQUEST
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_rate_limit_blocks_before_provider_call() -> None:
    tenant = uuid4()
    provider = DeterministicTestProvider()
    gateway = AIGateway(provider=provider, controller=controller(rpm=1))
    first = request().model_copy(update={"tenant_id": tenant})
    second = request().model_copy(update={"tenant_id": tenant})
    await gateway.execute(first)
    with pytest.raises(AIProviderError) as exc_info:
        await gateway.execute(second)
    assert exc_info.value.code == AIErrorCode.LOCAL_RATE_LIMIT
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_budget_limit_blocks_before_provider_call() -> None:
    provider = DeterministicTestProvider()
    gateway = AIGateway(provider=provider, controller=controller(budget="0.005"))
    with pytest.raises(AIProviderError) as exc_info:
        await gateway.execute(request(), estimated_cost_usd=Decimal("0.01"))
    assert exc_info.value.code == AIErrorCode.BUDGET_EXCEEDED
    assert provider.calls == 0

@pytest.mark.asyncio
async def test_failed_provider_request_releases_budget_reservation() -> None:
    tenant = uuid4()
    failure = AIProviderError("bad", code=AIErrorCode.INVALID_REQUEST, retryable=False, provider="test")
    control = controller(budget="0.01")
    failing = AIGateway(provider=DeterministicTestProvider(failures=[failure]), controller=control)
    req = request().model_copy(update={"tenant_id": tenant})
    with pytest.raises(AIProviderError):
        await failing.execute(req, estimated_cost_usd=Decimal("0.01"))
    succeeding = AIGateway(provider=DeterministicTestProvider(), controller=control)
    result = await succeeding.execute(request().model_copy(update={"tenant_id": tenant}), estimated_cost_usd=Decimal("0.01"))
    assert result.output_text == "deterministic-test-output"
