from __future__ import annotations

from collections import deque
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from verideploy.llm.contracts import AIProviderName, AIRequest, AIResult, AIUsage
from verideploy.llm.controls import InMemoryRequestController, LocalControlPolicy
from verideploy.llm.gateway import AIGateway
from verideploy.llm.openai_provider import OpenAIProvider
from verideploy.llm.persistence import InMemoryResponsePersistence
from verideploy.llm.structured_output import (
    STRUCTURED_VALIDATION_OUTCOME_ADAPTER,
    StructuredOutputEngine,
    StructuredOutputRepairPolicy,
    StructuredOutputValidationError,
    StructuredValidationAccepted,
    StructuredValidationRejected,
    validate_structured_text,
)
from verideploy.llm.structured_schemas import (
    EvidenceExtractionOutput,
    StructuredDecisionOutput,
    build_builtin_structured_registry,
)


def request() -> AIRequest:
    return AIRequest(
        tenant_id=uuid4(),
        correlation_id="corr",
        operation="evidence_fusion",
        model="test-model",
        input="Return the structured result.",
    )


def controller() -> InMemoryRequestController:
    return InMemoryRequestController(LocalControlPolicy(requests_per_minute=100, monthly_budget_usd=100))


class SequenceProvider:
    name = "test"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = deque(outputs)
        self.calls = 0

    async def execute(self, req: AIRequest) -> AIResult:
        self.calls += 1
        output = self.outputs.popleft()
        return AIResult(
            request_id=req.request_id,
            provider=AIProviderName.TEST,
            model=req.model or "",
            output_text=output,
            provider_response_id=f"resp-{req.request_id}-{self.calls}",
            usage=AIUsage(input_tokens=2, output_tokens=3, total_tokens=5),
            latency_ms=0,
            attempts=1,
        )

    async def stream(self, req):
        raise NotImplementedError

    async def cancel(self, response_id: str) -> bool:
        return True


def valid_evidence_json() -> str:
    return (
        '{"summary":"checkout latency evidence","findings":['
        '{"kind":"text","statement":"pool exhausted","evidence_ids":["ev-1"]},'
        '{"kind":"numeric","metric":"latency_p95","value":920.5,"unit":"ms","evidence_ids":["ev-2"]}'
        '],"limitations":[]}'
    )


def test_registry_exports_closed_json_schema_and_discriminated_union() -> None:
    registry = build_builtin_structured_registry()
    definition = registry.get("evidence_extraction", "1.0.0")
    schema = definition.json_schema()
    assert schema["additionalProperties"] is False
    finding_schema = schema["properties"]["findings"]["items"]
    assert "oneOf" in finding_schema or "anyOf" in finding_schema
    assert finding_schema.get("discriminator", {}).get("propertyName") == "kind"


def test_discriminated_union_rejects_wrong_variant_shape() -> None:
    with pytest.raises(ValidationError):
        EvidenceExtractionOutput.model_validate(
            {
                "summary": "x",
                "findings": [{"kind": "numeric", "statement": "not numeric", "evidence_ids": ["ev-1"]}],
                "limitations": [],
            }
        )


def test_structured_validation_outcome_is_discriminated() -> None:
    accepted = STRUCTURED_VALIDATION_OUTCOME_ADAPTER.validate_python(
        {"status": "accepted", "schema_name": "x", "schema_version": "1.0.0", "local_repair_applied": False}
    )
    rejected = STRUCTURED_VALIDATION_OUTCOME_ADAPTER.validate_python(
        {"status": "rejected", "schema_name": "x", "schema_version": "1.0.0", "error_count": 2}
    )
    assert isinstance(accepted, StructuredValidationAccepted)
    assert isinstance(rejected, StructuredValidationRejected)


def test_local_repair_only_unwraps_json_without_type_coercion() -> None:
    definition = build_builtin_structured_registry().get("evidence_extraction", "1.0.0")
    parsed, repaired = validate_structured_text(definition, f"```json\n{valid_evidence_json()}\n```")
    assert repaired is True
    assert isinstance(parsed, EvidenceExtractionOutput)

    invalid = valid_evidence_json().replace('"value":920.5', '"value":"920.5"')
    with pytest.raises(StructuredOutputValidationError):
        validate_structured_text(definition, invalid)


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp-structured",
            status="completed",
            output_text=valid_evidence_json(),
            output=[],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2),
        )


@pytest.mark.asyncio
async def test_openai_responses_mapping_uses_strict_text_format() -> None:
    fake = FakeResponses()
    provider = OpenAIProvider(api_key="test-only", timeout_seconds=1, client=SimpleNamespace(responses=fake))
    definition = build_builtin_structured_registry().get("evidence_extraction", "1.0.0")
    await provider.execute(request().model_copy(update={"structured_output": definition.provider_format()}))
    fmt = fake.calls[0]["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["name"] == "evidence_extraction"
    assert fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_invalid_structured_output_is_not_persisted() -> None:
    persistence = InMemoryResponsePersistence()
    provider = SequenceProvider(['{"summary":"missing fields"}'])
    gateway = AIGateway(provider=provider, controller=controller(), response_persistence=persistence, max_attempts=1)
    engine = StructuredOutputEngine(registry=build_builtin_structured_registry(), gateway=gateway)
    req = request()
    with pytest.raises(StructuredOutputValidationError):
        await engine.execute(
            req,
            schema_name="evidence_extraction",
            schema_version="1.0.0",
            policy=StructuredOutputRepairPolicy(max_provider_attempts=1),
        )
    assert await persistence.get(tenant_id=req.tenant_id, provider_response_id=f"resp-{req.request_id}-1") is None


@pytest.mark.asyncio
async def test_engine_retries_invalid_output_and_persists_only_valid_result() -> None:
    persistence = InMemoryResponsePersistence()
    provider = SequenceProvider(['{"summary":"bad"}', valid_evidence_json()])
    gateway = AIGateway(provider=provider, controller=controller(), response_persistence=persistence, max_attempts=1)
    engine = StructuredOutputEngine(registry=build_builtin_structured_registry(), gateway=gateway)
    req = request()
    result, parsed, outcome = await engine.execute(
        req,
        schema_name="evidence_extraction",
        schema_version="1.0.0",
        policy=StructuredOutputRepairPolicy(max_provider_attempts=2),
    )
    assert provider.calls == 2
    assert isinstance(parsed, EvidenceExtractionOutput)
    assert outcome.status == "accepted"
    assert await persistence.get(tenant_id=req.tenant_id, provider_response_id=result.provider_response_id or "") is not None
    assert [event.outcome for event in engine.telemetry.events][:2] == ["invalid", "valid"]


@pytest.mark.asyncio
async def test_retry_exhaustion_returns_sanitized_errors_not_raw_output() -> None:
    raw = '{"password":"should-not-appear","summary":"bad"}'
    provider = SequenceProvider([raw, raw])
    gateway = AIGateway(provider=provider, controller=controller(), max_attempts=1)
    engine = StructuredOutputEngine(registry=build_builtin_structured_registry(), gateway=gateway)
    with pytest.raises(StructuredOutputValidationError) as exc_info:
        await engine.execute(
            request(), schema_name="evidence_extraction", schema_version="1.0.0", policy=StructuredOutputRepairPolicy(max_provider_attempts=2)
        )
    assert "should-not-appear" not in str(exc_info.value.errors)
    assert engine.telemetry.events[-1].outcome == "retry_exhausted"


def test_registry_exports_deterministic_json_and_typescript(tmp_path: Path) -> None:
    registry = build_builtin_structured_registry()
    written = registry.export_json_schemas(tmp_path / "schemas")
    ts = registry.export_typescript(tmp_path / "contracts.ts")
    assert any(path.name == "manifest.json" for path in written)
    content = ts.read_text(encoding="utf-8")
    assert "EvidenceExtractionV1_0_0" in content
    assert '"kind": "text"' not in content  # generated contract is a type, not sample data
    assert '"summary": string' in content


def test_structured_decision_schema_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        StructuredDecisionOutput.model_validate(
            {
                "result": {"decision": "proceed", "rationale": "supported", "evidence_ids": ["ev-1"], "extra": 1},
                "confidence": 0.9,
            }
        )
