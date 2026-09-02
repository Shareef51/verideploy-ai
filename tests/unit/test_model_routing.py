from decimal import Decimal
from uuid import uuid4

import pytest

from verideploy.llm.audit import InMemoryRoutingAuditSink
from verideploy.llm.concurrency import RoleConcurrencyLimiter
from verideploy.llm.contracts import AIRequest
from verideploy.llm.controls import InMemoryRequestController, LocalControlPolicy
from verideploy.llm.errors import AIErrorCode, AIProviderError
from verideploy.llm.gateway import AIGateway
from verideploy.llm.pricing import CostCalculator, ModelPrice, PricingCatalog
from verideploy.llm.routing import ModelBinding, ModelRole, ModelRouter, RoutingPolicy
from verideploy.llm.test_provider import DeterministicTestProvider


def router() -> ModelRouter:
    return ModelRouter(
        RoutingPolicy(
            bindings={
                ModelRole.FAST: ModelBinding("fast-model", ("fast-fallback",)),
                ModelRole.STANDARD: ModelBinding("standard-model", ("standard-fallback",)),
                ModelRole.REASONING: ModelBinding("reasoning-model", ("reasoning-fallback",)),
            },
            operation_overrides={"tenant_sensitive_summary": ModelRole.REASONING},
            allow_explicit_model_override=True,
        )
    )


def catalog() -> PricingCatalog:
    return PricingCatalog.model_validate(
        {
            "catalog_version": "test-v1",
            "effective_at": "2026-08-16T00:00:00Z",
            "source": "test catalog",
            "models": {
                "fast-model": {"input_per_million_usd": "0.20", "output_per_million_usd": "1.20"},
                "fast-fallback": {"input_per_million_usd": "0.20", "output_per_million_usd": "1.20"},
                "standard-model": {"input_per_million_usd": "2.00", "output_per_million_usd": "12.00"},
                "standard-fallback": {"input_per_million_usd": "2.00", "output_per_million_usd": "12.00"},
                "reasoning-model": {"input_per_million_usd": "5.00", "output_per_million_usd": "30.00"},
                "reasoning-fallback": {"input_per_million_usd": "5.00", "output_per_million_usd": "30.00"}
            },
        }
    )


def controller() -> InMemoryRequestController:
    return InMemoryRequestController(LocalControlPolicy(100, Decimal("100")))


def request(operation: str, role: ModelRole | None = None, model: str | None = None) -> AIRequest:
    return AIRequest(
        tenant_id=uuid4(),
        correlation_id="corr",
        operation=operation,
        model_role=role,
        model=model,
        input="Investigate this deployment signal and return a concise result.",
        max_output_tokens=100,
    )


def test_deterministic_workload_routing_and_overrides() -> None:
    r = router()
    assert r.route(operation="intent_classification").role is ModelRole.FAST
    assert r.route(operation="release_risk").role is ModelRole.STANDARD
    assert r.route(operation="complex_rca").role is ModelRole.REASONING
    decision = r.route(operation="tenant_sensitive_summary")
    assert decision.role is ModelRole.REASONING and decision.policy_override is True
    explicit = r.route(operation="release_risk", explicit_model="standard-fallback")
    assert explicit.primary_model == "standard-fallback" and explicit.fallback_models == ()


def test_pricing_calculator_estimate_and_actual_usage() -> None:
    calc = CostCalculator(catalog())
    estimate = calc.estimate(model="standard-model", input_text="x" * 400, max_output_tokens=100)
    assert estimate.priced is True and estimate.estimated_input_tokens == 100
    actual = calc.actual(
        model="standard-model",
        usage=__import__("verideploy.llm.contracts", fromlist=["AIUsage"]).AIUsage(input_tokens=1000, output_tokens=500),
    )
    assert actual.actual_cost_usd == Decimal("0.008000")


@pytest.mark.asyncio
async def test_gateway_routes_prices_and_records_audit() -> None:
    audit = InMemoryRoutingAuditSink()
    provider = DeterministicTestProvider()
    gateway = AIGateway(
        provider=provider,
        controller=controller(),
        router=router(),
        cost_calculator=CostCalculator(catalog()),
        concurrency_limiter=RoleConcurrencyLimiter({ModelRole.FAST: 2, ModelRole.STANDARD: 2, ModelRole.REASONING: 1}),
        routing_audit=audit,
        max_attempts=1,
    )
    result = await gateway.execute(request("complex_rca"))
    assert result.model_role is ModelRole.REASONING
    assert result.model == "reasoning-model"
    assert result.route_reason == "deterministic_workload_rule"
    assert result.actual_cost_usd is not None
    records = await audit.records()
    assert len(records) == 1
    assert records[0].resolved_model == "reasoning-model"
    assert records[0].role is ModelRole.REASONING
    assert records[0].retry_count == 0


@pytest.mark.asyncio
async def test_retryable_primary_failure_uses_configured_fallback() -> None:
    provider = DeterministicTestProvider(
        failures=[
            AIProviderError(
                "busy",
                code=AIErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
                provider="test",
            )
        ]
    )
    audit = InMemoryRoutingAuditSink()
    gateway = AIGateway(
        provider=provider,
        controller=controller(),
        router=router(),
        cost_calculator=CostCalculator(catalog()),
        routing_audit=audit,
        max_attempts=1,
    )
    result = await gateway.execute(request("release_risk"))
    assert result.model == "standard-fallback"
    assert result.fallback_index == 1
    records = await audit.records()
    assert [r.resolved_model for r in records] == ["standard-model", "standard-fallback"]
    assert records[0].outcome.startswith("error:") and records[1].outcome == "success"


@pytest.mark.asyncio
async def test_non_retryable_auth_error_never_falls_back() -> None:
    provider = DeterministicTestProvider(
        failures=[AIProviderError("auth", code=AIErrorCode.AUTHENTICATION, retryable=False, provider="test")]
    )
    gateway = AIGateway(
        provider=provider,
        controller=controller(),
        router=router(),
        cost_calculator=CostCalculator(catalog()),
        max_attempts=1,
    )
    with pytest.raises(AIProviderError) as exc:
        await gateway.execute(request("release_risk"))
    assert exc.value.code is AIErrorCode.AUTHENTICATION
    assert provider.calls == 1


def test_production_style_router_rejects_explicit_model_bypass() -> None:
    locked = ModelRouter(
        RoutingPolicy(
            bindings={
                ModelRole.FAST: ModelBinding("fast-model"),
                ModelRole.STANDARD: ModelBinding("standard-model"),
                ModelRole.REASONING: ModelBinding("reasoning-model"),
            }
        )
    )
    with pytest.raises(ValueError, match="disabled"):
        locked.route(operation="release_risk", explicit_model="standard-model")
