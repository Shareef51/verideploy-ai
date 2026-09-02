from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from verideploy.llm.structured_output import StructuredSchemaRegistry


class TextEvidenceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["text"]
    statement: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(min_length=1, max_length=32)


class NumericEvidenceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["numeric"]
    metric: str = Field(min_length=1, max_length=256)
    value: float
    unit: str | None
    evidence_ids: list[str] = Field(min_length=1, max_length=32)


EvidenceFinding = Annotated[TextEvidenceFinding | NumericEvidenceFinding, Field(discriminator="kind")]


class EvidenceExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1, max_length=8000)
    findings: list[EvidenceFinding] = Field(max_length=128)
    limitations: list[str] = Field(max_length=64)


class DecisionProceed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["proceed"]
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(min_length=1, max_length=64)


class DecisionEscalate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["escalate"]
    rationale: str = Field(min_length=1, max_length=4000)
    missing_evidence: list[str] = Field(max_length=64)


DecisionResult = Annotated[DecisionProceed | DecisionEscalate, Field(discriminator="decision")]


class StructuredDecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    result: DecisionResult
    confidence: float = Field(ge=0, le=1)


def build_builtin_structured_registry() -> StructuredSchemaRegistry:
    registry = StructuredSchemaRegistry()
    registry.register(
        name="evidence_extraction",
        version="1.0.0",
        model=EvidenceExtractionOutput,
        description="Evidence-grounded extraction with discriminated text and numeric findings.",
    )
    registry.register(
        name="structured_decision",
        version="1.0.0",
        model=StructuredDecisionOutput,
        description="Bounded proceed-or-escalate decision contract.",
    )
    return registry
