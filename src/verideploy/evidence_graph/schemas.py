from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GraphEntityType(StrEnum):
    PULL_REQUEST = "pull_request"
    COMMIT = "commit"
    RELEASE = "release"
    SERVICE = "service"
    INCIDENT = "incident"
    ROOT_CAUSE = "root_cause"
    EVIDENCE = "evidence"
    TEAM = "team"
    ENVIRONMENT = "environment"


class GraphRelationship(StrEnum):
    MODIFIES_SERVICE = "modifies_service"
    CONTAINS_COMMIT = "contains_commit"
    DEPLOYED_AS = "deployed_as"
    EXPERIENCED_INCIDENT = "experienced_incident"
    CAUSED_BY = "caused_by"
    SUPPORTED_BY = "supported_by"
    CORRELATES_WITH = "correlates_with"
    DERIVED_FROM = "derived_from"
    OCCURRED_BEFORE = "occurred_before"
    DEPENDS_ON = "depends_on"
    OWNED_BY = "owned_by"
    RUNS_IN = "runs_in"


class GraphEntityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: UUID
    entity_type: GraphEntityType
    natural_key: str = Field(min_length=1, max_length=512)
    label: str = Field(min_length=1, max_length=512)
    reference_uri: str = Field(min_length=3, max_length=2048)
    evidence_record_id: UUID | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None

    @field_validator("tenant_id", "evidence_record_id", mode="before")
    @classmethod
    def parse_uuid(cls, value: Any) -> Any:
        return UUID(value) if isinstance(value, str) else value

    @field_validator("entity_type", mode="before")
    @classmethod
    def parse_entity_type(cls, value: Any) -> Any:
        return GraphEntityType(value) if isinstance(value, str) else value

    @field_validator("observed_at", mode="before")
    @classmethod
    def parse_time(cls, value: Any) -> Any:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_time(self) -> "GraphEntityCreate":
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return self


class GraphEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    entity_id: UUID
    tenant_id: UUID
    entity_type: GraphEntityType
    natural_key: str
    label: str
    reference_uri: str
    evidence_record_id: UUID | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None
    created_at: datetime

    @field_validator("entity_type", mode="before")
    @classmethod
    def parse_entity_type(cls, value: Any) -> Any:
        return GraphEntityType(value) if isinstance(value, str) else value


class GraphEdgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relationship: GraphRelationship
    confidence: float = Field(ge=0.0, le=1.0)
    occurred_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tenant_id", "source_entity_id", "target_entity_id", mode="before")
    @classmethod
    def parse_uuid(cls, value: Any) -> Any:
        return UUID(value) if isinstance(value, str) else value

    @field_validator("relationship", mode="before")
    @classmethod
    def parse_relationship(cls, value: Any) -> Any:
        return GraphRelationship(value) if isinstance(value, str) else value

    @field_validator("occurred_at", "valid_from", "valid_to", mode="before")
    @classmethod
    def parse_time(cls, value: Any) -> Any:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_edge(self) -> "GraphEdgeCreate":
        if self.source_entity_id == self.target_entity_id:
            raise ValueError("graph self-edges are not allowed")
        for value in (self.occurred_at, self.valid_from, self.valid_to):
            if value is not None and value.tzinfo is None:
                raise ValueError("graph edge timestamps must be timezone-aware")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot precede valid_from")
        return self


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    edge_id: UUID
    tenant_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relationship: GraphRelationship
    confidence: float
    occurred_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("relationship", mode="before")
    @classmethod
    def parse_relationship(cls, value: Any) -> Any:
        return GraphRelationship(value) if isinstance(value, str) else value


class GraphPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    entities: tuple[GraphEntity, ...]
    edges: tuple[GraphEdge, ...]


class GraphSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    tenant_id: UUID
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entities: tuple[GraphEntity, ...]
    edges: tuple[GraphEdge, ...]


def entity_id_for(tenant_id: UUID, entity_type: GraphEntityType, natural_key: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"verideploy:graph:{tenant_id}:{entity_type.value}:{natural_key}")


def edge_id_for(tenant_id: UUID, source: UUID, relationship: GraphRelationship, target: UUID, occurred_at: datetime | None) -> UUID:
    when = occurred_at.isoformat() if occurred_at else "none"
    return uuid.uuid5(uuid.NAMESPACE_URL, f"verideploy:graph-edge:{tenant_id}:{source}:{relationship.value}:{target}:{when}")


def snapshot_sha256(entities: tuple[GraphEntity, ...], edges: tuple[GraphEdge, ...]) -> str:
    payload = {
        "entities": [e.model_dump(mode="json") for e in sorted(entities, key=lambda x: str(x.entity_id))],
        "edges": [e.model_dump(mode="json") for e in sorted(edges, key=lambda x: str(x.edge_id))],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()
