import json
from pathlib import Path

import pytest

from verideploy.config import Settings
from verideploy.llm.factory import build_model_router, load_pricing_catalog
from verideploy.llm.routing import ModelRole


def configured_settings(**overrides):
    base = dict(
        app_env="development",
        openai_fast_model="fast-a",
        openai_standard_model="standard-a",
        openai_reasoning_model="reasoning-a",
        openai_fast_fallback_models="fast-b,fast-c",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_factory_builds_environment_driven_bindings() -> None:
    decision = build_model_router(configured_settings()).route(operation="metadata_extraction")
    assert decision.role is ModelRole.FAST
    assert decision.ordered_models == ("fast-a", "fast-b", "fast-c")


def test_factory_applies_json_operation_override() -> None:
    decision = build_model_router(configured_settings(ai_operation_role_overrides_json='{"release_risk":"reasoning"}')).route(operation="release_risk")
    assert decision.role is ModelRole.REASONING
    assert decision.reason == "operation_policy_override"


def test_production_requires_all_role_bindings() -> None:
    with pytest.raises(ValueError, match="model bindings"):
        Settings(
            _env_file=None,
            app_env="production",
            app_secret_key="x" * 40,
            ai_control_backend="redis",
            openai_api_key="runtime-secret",
            openai_fast_model="fast-a",
            openai_standard_model="standard-a",
            openai_reasoning_model=None,
        )


def test_production_rejects_unpriced_configured_model(tmp_path: Path) -> None:
    catalog = tmp_path / "pricing.json"
    catalog.write_text(
        json.dumps(
            {
                "catalog_version": "v1",
                "effective_at": "2026-08-16T00:00:00Z",
                "source": "operator catalog",
                "models": {
                    "fast-a": {"input_per_million_usd": 1, "output_per_million_usd": 2},
                    "standard-a": {"input_per_million_usd": 1, "output_per_million_usd": 2}
                }
            }
        )
    )
    settings = configured_settings(
        app_env="production",
        app_secret_key="x" * 40,
        ai_control_backend="redis",
        openai_api_key="runtime-secret",
        ai_pricing_catalog_path=str(catalog),
        openai_fast_fallback_models="",
    )
    with pytest.raises(ValueError, match="reasoning-a"):
        load_pricing_catalog(settings)
