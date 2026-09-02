from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from verideploy.config import Settings
from verideploy.langsmith_integration.service import (
    LangSmithDatasetHook,
    LangSmithObserver,
    NullLangSmithObserver,
    build_langsmith_observer,
)
from verideploy.llm.contracts import AIRequest
from verideploy.llm.controls import InMemoryRequestController, LocalControlPolicy
from verideploy.llm.errors import AIErrorCode, AIProviderError
from verideploy.llm.gateway import AIGateway
from verideploy.llm.test_provider import DeterministicTestProvider

ROOT = Path(__file__).resolve().parents[2]


class FakeLangSmithClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.created: list[dict] = []
        self.updated: list[tuple[object, dict]] = []
        self.datasets: set[str] = set()
        self.examples: list[dict] = []

    def create_run(self, **kwargs):
        if self.fail:
            raise RuntimeError("langsmith unavailable")
        self.created.append(kwargs)

    def update_run(self, run_id, **kwargs):
        if self.fail:
            raise RuntimeError("langsmith unavailable")
        self.updated.append((run_id, kwargs))

    def has_dataset(self, *, dataset_name: str) -> bool:
        return dataset_name in self.datasets

    def create_dataset(self, *, dataset_name: str, description: str):
        self.datasets.add(dataset_name)
        return {"name": dataset_name, "description": description}

    def create_example(self, **kwargs):
        self.examples.append(kwargs)


def _request() -> AIRequest:
    return AIRequest(
        tenant_id=uuid4(),
        correlation_id="corr",
        operation=".test",
        model="test-model",
        input="authorized synthetic input",
        metadata={"prompt_name": "rca", "prompt_version": "1.3", "prompt_sha256": "a" * 64},
    )


def _controller() -> InMemoryRequestController:
    return InMemoryRequestController(LocalControlPolicy(requests_per_minute=20, monthly_budget_usd=Decimal("10")))


def test_disabled_observer_is_noop_and_does_not_require_sdk() -> None:
    settings = Settings(app_env="test", ai_provider="test", langsmith_enabled=False)
    observer = build_langsmith_observer(settings)
    assert isinstance(observer, NullLangSmithObserver)
    assert observer.status.enabled is False
    assert observer.status.project_name == "verideploy-test"


@pytest.mark.asyncio
async def test_run_hierarchy_uses_correlation_root_and_llm_child() -> None:
    client = FakeLangSmithClient()
    observer = LangSmithObserver(client=client, environment="test", project_name="verideploy-test")
    req = _request()
    result = await AIGateway(
        provider=DeterministicTestProvider(output_text="ok"),
        controller=_controller(),
        langsmith_observer=observer,
    ).execute(req)
    assert result.output_text == "ok"
    assert len(client.created) == 2
    root, child = client.created
    assert root["run_type"] == "chain"
    assert child["run_type"] == "llm"
    assert child["parent_run_id"] == root["id"]
    assert child["extra"]["metadata"]["correlation_id"] == req.correlation_id
    assert child["extra"]["metadata"]["prompt_version"] == "1.3"


@pytest.mark.asyncio
async def test_enabling_observability_cannot_change_success_result() -> None:
    req = _request()
    baseline = await AIGateway(provider=DeterministicTestProvider(output_text="same"), controller=_controller()).execute(req)
    broken = LangSmithObserver(client=FakeLangSmithClient(fail=True), environment="test", project_name="verideploy-test")
    observed = await AIGateway(
        provider=DeterministicTestProvider(output_text="same"), controller=_controller(), langsmith_observer=broken
    ).execute(req)
    assert observed.output_text == baseline.output_text == "same"
    assert observed.provider == baseline.provider
    assert broken.status.last_error is not None


@pytest.mark.asyncio
async def test_enabling_observability_cannot_change_business_failure() -> None:
    err = AIProviderError("bad request", code=AIErrorCode.INVALID_REQUEST, retryable=False, provider="test")
    broken = LangSmithObserver(client=FakeLangSmithClient(fail=True), environment="test", project_name="verideploy-test")
    with pytest.raises(AIProviderError) as exc:
        await AIGateway(
            provider=DeterministicTestProvider(failures=[err]), controller=_controller(), langsmith_observer=broken
        ).execute(_request())
    assert exc.value.code == AIErrorCode.INVALID_REQUEST


def test_metadata_redaction_happens_before_generic_span_export() -> None:
    client = FakeLangSmithClient()
    observer = LangSmithObserver(client=client, environment="staging", project_name="verideploy-staging")
    observer.trace_fact(
        tenant_id=uuid4(),
        correlation_id="corr-redact",
        span_key="tool:1",
        name="mcp.github",
        run_type="tool",
        inputs={"repo": "payments", "api_key": "do-not-export"},
        outputs={"authorization": "secret", "status": "ok"},
        metadata={"password": "x", "safe": "y"},
    )
    child = client.created[-1]
    assert child["inputs"]["api_key"] == "[REDACTED]"
    assert child["extra"]["metadata"]["password"] == "[REDACTED]"
    assert client.updated[-1][1]["outputs"]["authorization"] == "[REDACTED]"


def test_environment_separation_is_explicit() -> None:
    for env in ("development", "test", "staging", "production"):
        settings = Settings(
            app_env=env,
            app_secret_key="x" * 40,
            ai_provider="test",
            ai_control_backend="redis" if env == "production" else "memory",
            openai_fast_model="x" if env in {"staging", "production"} else None,
            openai_standard_model="x" if env in {"staging", "production"} else None,
            openai_reasoning_model="x" if env in {"staging", "production"} else None,
            langsmith_enabled=False,
            langsmith_project_prefix="verideploy",
        )
        assert build_langsmith_observer(settings).status.project_name == f"verideploy-{env}"


def test_dataset_hook_is_explicit_opt_in_and_redacted() -> None:
    client = FakeLangSmithClient()
    disabled = LangSmithDatasetHook(client=client, enabled=False, environment="test", dataset_prefix="verideploy-evals")
    assert disabled.export_example(logical_dataset="rca", inputs={"x": 1}) is False
    enabled = LangSmithDatasetHook(client=client, enabled=True, environment="test", dataset_prefix="verideploy-evals")
    assert enabled.export_example(
        logical_dataset="rca",
        inputs={"question": "q", "api_key": "secret"},
        outputs={"answer": "a"},
        metadata={"password": "secret", "source": "synthetic"},
    ) is True
    assert "verideploy-evals-test-rca" in client.datasets
    example = client.examples[-1]
    assert example["inputs"]["api_key"] == "[REDACTED]"
    assert example["metadata"]["password"] == "[REDACTED]"
    assert example["metadata"]["environment"] == "test"


def test_production_enabled_langsmith_requires_api_key() -> None:
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        Settings(
            app_env="production",
            app_secret_key="x" * 40,
            ai_provider="test",
            ai_control_backend="redis",
            openai_fast_model="x",
            openai_standard_model="x",
            openai_reasoning_model="x",
            langsmith_enabled=True,
        )


def test_service_factory_and_status_api_contract() -> None:
    factory = (ROOT / "services/ai/langsmith.py").read_text()
    route = (ROOT / "services/ai/routes/langsmith.py").read_text()
    gateway = (ROOT / "services/ai/ai_gateway.py").read_text()
    assert "build_langsmith_observer" in factory
    assert '"/status"' in route
    assert "get_langsmith_observer()" in gateway


def test_dependency_config_and_version_contract() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    env = (ROOT / ".env.example").read_text()
    assert '"langsmith>=0.3,<1"' in pyproject
    assert "LANGSMITH_ENABLED=false" in env
    import verideploy
    assert tuple(map(int, verideploy.__version__.split("."))) >= (0, 49, 0)
