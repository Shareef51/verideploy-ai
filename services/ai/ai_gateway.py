from __future__ import annotations

from functools import lru_cache

from verideploy.config import get_settings
from verideploy.llm.controls import InMemoryRequestController, LocalControlPolicy, RedisRequestController
from verideploy.llm.factory import build_concurrency_limiter, build_cost_calculator, build_model_router
from verideploy.llm.gateway import AIGateway
from verideploy.llm.openai_provider import OpenAIProvider
from verideploy.llm.persistence import SqlAlchemyResponsePersistence
from verideploy.llm.test_provider import DeterministicTestProvider
from verideploy.llmops.sinks import LLMOpsModelCallSink
from services.ai.llmops import get_llmops_service
from services.ai.langsmith import get_langsmith_observer


@lru_cache
def get_ai_gateway() -> AIGateway:
    settings = get_settings()
    if settings.ai_control_backend == "redis":
        controller = RedisRequestController(
            settings.redis_url,
            requests_per_minute=settings.ai_requests_per_minute,
            monthly_budget_usd=settings.ai_monthly_budget_usd,
        )
    else:
        controller = InMemoryRequestController(
            LocalControlPolicy(
                requests_per_minute=settings.ai_requests_per_minute,
                monthly_budget_usd=settings.ai_monthly_budget_usd,
            )
        )

    if settings.ai_provider == "test":
        provider = DeterministicTestProvider()
    else:
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        provider = OpenAIProvider(api_key=api_key, timeout_seconds=settings.ai_timeout_seconds)

    configured_roles = all(
        (settings.openai_fast_model, settings.openai_standard_model, settings.openai_reasoning_model)
    )
    router = build_model_router(settings) if configured_roles else None

    return AIGateway(
        provider=provider,
        controller=controller,
        router=router,
        cost_calculator=build_cost_calculator(settings),
        concurrency_limiter=build_concurrency_limiter(settings),
        llmops_sink=LLMOpsModelCallSink(get_llmops_service()),
        langsmith_observer=get_langsmith_observer(),
        response_persistence=SqlAlchemyResponsePersistence(
            settings.database_url,
            create_schema=settings.app_env == "test",
        ),
        max_attempts=settings.ai_max_attempts,
    )
