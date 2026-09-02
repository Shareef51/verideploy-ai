from __future__ import annotations

import json
from pathlib import Path

from verideploy.config import Settings
from verideploy.llm.concurrency import RoleConcurrencyLimiter
from verideploy.llm.pricing import CostCalculator, PricingCatalog
from verideploy.llm.routing import ModelBinding, ModelRole, ModelRouter, RoutingPolicy


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def build_model_router(settings: Settings) -> ModelRouter:
    required = {
        ModelRole.FAST: settings.openai_fast_model,
        ModelRole.STANDARD: settings.openai_standard_model,
        ModelRole.REASONING: settings.openai_reasoning_model,
    }
    missing = [role.value for role, model in required.items() if not model]
    if missing:
        raise ValueError(f"missing configured models for roles: {', '.join(sorted(missing))}")
    raw_overrides = json.loads(settings.ai_operation_role_overrides_json)
    if not isinstance(raw_overrides, dict):
        raise ValueError("AI_OPERATION_ROLE_OVERRIDES_JSON must be a JSON object")
    overrides: dict[str, ModelRole] = {}
    for operation, role in raw_overrides.items():
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation override keys must be non-empty strings")
        try:
            overrides[operation.strip().lower()] = ModelRole(str(role).lower())
        except ValueError as exc:
            raise ValueError(f"invalid model role override for {operation}: {role}") from exc
    return ModelRouter(
        RoutingPolicy(
            bindings={
                ModelRole.FAST: ModelBinding(required[ModelRole.FAST] or "", _csv(settings.openai_fast_fallback_models)),
                ModelRole.STANDARD: ModelBinding(
                    required[ModelRole.STANDARD] or "", _csv(settings.openai_standard_fallback_models)
                ),
                ModelRole.REASONING: ModelBinding(
                    required[ModelRole.REASONING] or "", _csv(settings.openai_reasoning_fallback_models)
                ),
            },
            operation_overrides=overrides,
        )
    )


def load_pricing_catalog(settings: Settings) -> PricingCatalog | None:
    path = Path(settings.ai_pricing_catalog_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        if settings.app_env in {"staging", "production"}:
            raise ValueError(f"AI pricing catalog not found: {path}")
        return None
    catalog = PricingCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if settings.app_env in {"staging", "production"}:
        configured = {
            model
            for model in (
                settings.openai_fast_model,
                settings.openai_standard_model,
                settings.openai_reasoning_model,
                *_csv(settings.openai_fast_fallback_models),
                *_csv(settings.openai_standard_fallback_models),
                *_csv(settings.openai_reasoning_fallback_models),
            )
            if model
        }
        unpriced = sorted(configured.difference(catalog.models))
        if unpriced and not settings.ai_allow_unpriced_models:
            raise ValueError(f"configured models missing from pricing catalog: {', '.join(unpriced)}")
    return catalog


def build_cost_calculator(settings: Settings) -> CostCalculator:
    return CostCalculator(load_pricing_catalog(settings))


def build_concurrency_limiter(settings: Settings) -> RoleConcurrencyLimiter:
    return RoleConcurrencyLimiter(
        {
            ModelRole.FAST: settings.ai_fast_concurrency,
            ModelRole.STANDARD: settings.ai_standard_concurrency,
            ModelRole.REASONING: settings.ai_reasoning_concurrency,
        }
    )
