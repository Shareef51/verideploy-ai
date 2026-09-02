from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceKind(StrEnum):
    DOCUMENT = "document"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    EVENT = "event"
    RELEASE = "release"
    INCIDENT = "incident"
    ANALYSIS = "analysis"


class RetentionClass(StrEnum):
    OPERATING = "operating"
    AUDIT = "audit"
    HISTORICAL = "historical"


class ParentRelation(StrEnum):
    DERIVED_FROM = "derived_from"
    VERSION_OF = "version_of"
    EXTRACTED_FROM = "extracted_from"
    CORRELATED_FROM = "correlated_from"


class ObjectReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    uri: str = Field(min_length=3, max_length=2048)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=3, max_length=255)
    size_bytes: int = Field(ge=0)
    version_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def safe_uri(self) -> "ObjectReference":
        if not (self.uri.startswith("s3://") or self.uri.startswith("minio://") or self.uri.startswith("file://")):
            raise ValueError("object URI must use s3://, minio://, or file://")
        return self


class SourceLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source_system: str = Field(min_length=1, max_length=128)
    source_record_id: str = Field(min_length=1, max_length=512)
    locator: str = Field(min_length=1, max_length=2048)
    observed_at: datetime | None = None

    @field_validator("observed_at", mode="before")
    @classmethod
    def parse_observed_at(cls, value: Any) -> Any:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @model_validator(mode="after")
    def aware_time(self) -> "SourceLocator":
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return self


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    producer: str = Field(min_length=1, max_length=128)
    method: str = Field(min_length=1, max_length=128)
    source_locator: SourceLocator
    correlation_id: str = Field(min_length=1, max_length=128)
    synthetic: bool = False


class ConfidenceInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source_confidence: float = Field(ge=0.0, le=1.0)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    temporal_confidence: float = Field(ge=0.0, le=1.0)
    corroboration_count: int = Field(ge=0, le=10000)
    notes: tuple[str, ...] = Field(default_factory=tuple, max_length=16)

    @field_validator("notes", mode="before")
    @classmethod
    def parse_notes(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    retention_class: RetentionClass
    retain_until: datetime
    legal_hold: bool = False

    @field_validator("retention_class", mode="before")
    @classmethod
    def parse_retention_class(cls, value: Any) -> Any:
        return RetentionClass(value) if isinstance(value, str) else value

    @field_validator("retain_until", mode="before")
    @classmethod
    def parse_retain_until(cls, value: Any) -> Any:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @model_validator(mode="after")
    def aware_time(self) -> "RetentionPolicy":
        if self.retain_until.tzinfo is None:
            raise ValueError("retain_until must be timezone-aware")
        return self


class EvidenceParent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    parent_record_id: UUID

    @field_validator("parent_record_id", mode="before")
    @classmethod
    def parse_parent_id(cls, value: Any) -> Any:
        return UUID(value) if isinstance(value, str) else value
    relation: ParentRelation = ParentRelation.DERIVED_FROM

    @field_validator("relation", mode="before")
    @classmethod
    def parse_relation(cls, value: Any) -> Any:
        return ParentRelation(value) if isinstance(value, str) else value


class EvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: UUID
    evidence_id: UUID
    kind: EvidenceKind
    content: dict[str, Any]
    object_reference: ObjectReference | None = None
    confidence_inputs: ConfidenceInputs
    provenance: Provenance
    retention: RetentionPolicy
    parents: tuple[EvidenceParent, ...] = Field(default_factory=tuple, max_length=32)
    derived: bool = False

    @field_validator("parents", mode="before")
    @classmethod
    def parse_parents(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("kind", mode="before")
    @classmethod
    def parse_kind(cls, value: Any) -> Any:
        return EvidenceKind(value) if isinstance(value, str) else value

    @field_validator("tenant_id", "evidence_id", mode="before")
    @classmethod
    def parse_ids(cls, value: Any) -> Any:
        return UUID(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def derivative_requires_parent(self) -> "EvidenceCreate":
        if self.derived and not self.parents:
            raise ValueError("derived evidence must reference at least one parent")
        parent_ids = [p.parent_record_id for p in self.parents]
        if len(parent_ids) != len(set(parent_ids)):
            raise ValueError("duplicate parent record IDs are not allowed")
        return self


class EvidenceVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: UUID
    evidence_id: UUID
    previous_record_id: UUID
    content: dict[str, Any]
    object_reference: ObjectReference | None = None
    confidence_inputs: ConfidenceInputs
    provenance: Provenance
    retention: RetentionPolicy
    additional_parents: tuple[EvidenceParent, ...] = Field(default_factory=tuple, max_length=31)

    @field_validator("additional_parents", mode="before")
    @classmethod
    def parse_additional_parents(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("tenant_id", "evidence_id", "previous_record_id", mode="before")
    @classmethod
    def parse_ids(cls, value: Any) -> Any:
        return UUID(value) if isinstance(value, str) else value


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    record_id: UUID
    evidence_id: UUID
    tenant_id: UUID
    version: int = Field(ge=1)
    is_derived: bool = False
    kind: EvidenceKind
    content: dict[str, Any]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_reference: ObjectReference | None = None
    confidence_inputs: ConfidenceInputs
    provenance: Provenance
    retention: RetentionPolicy
    parents: tuple[EvidenceParent, ...] = Field(default_factory=tuple)
    created_at: datetime

    @field_validator("kind", mode="before")
    @classmethod
    def parse_record_kind(cls, value: Any) -> Any:
        return EvidenceKind(value) if isinstance(value, str) else value

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_created_at(cls, value: Any) -> Any:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class EvidenceLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    record: EvidenceRecord
    parents: tuple[EvidenceRecord, ...]
    children: tuple[EvidenceRecord, ...]


def canonical_content_sha256(content: dict[str, Any]) -> str:
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
