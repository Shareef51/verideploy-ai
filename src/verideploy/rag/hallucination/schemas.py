from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClaimSupportLabel(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNCERTAIN = "uncertain"


class ClaimReleaseAction(StrEnum):
    KEEP = "keep"
    REMOVE = "remove"
    QUALIFY = "qualify"


class ProposedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=4000)
    evidence_chunk_ids: tuple[UUID, ...] = ()
    material: bool = True
    proposed_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("claim text cannot be blank")
        return value


class EvidenceVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    chunk_id: UUID
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lexical_entailment: float = Field(ge=0.0, le=1.0)
    contradiction_score: float = Field(ge=0.0, le=1.0)
    prompt_injection_detected: bool = False
    ignored_instruction_lines: tuple[str, ...] = ()


class VerifiedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_id: str
    original_text: str
    released_text: str | None = None
    label: ClaimSupportLabel
    action: ClaimReleaseAction
    material: bool
    proposed_confidence: float = Field(ge=0.0, le=1.0)
    adjusted_confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[EvidenceVerification, ...] = ()
    reasons: tuple[str, ...] = ()


class HallucinationProtectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    self_corrective_run_id: UUID
    claims: list[ProposedClaim] = Field(min_length=1, max_length=64)


class HallucinationProtectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_id: UUID
    tenant_id: UUID
    self_corrective_run_id: UUID
    verifier_version: str
    protected: bool
    protected_answer: str
    claims: list[VerifiedClaim]
    supported_count: int = Field(ge=0)
    uncertain_count: int = Field(ge=0)
    unsupported_count: int = Field(ge=0)
    unsupported_material_rate: float = Field(ge=0.0, le=1.0)
    prompt_injection_evidence_count: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
