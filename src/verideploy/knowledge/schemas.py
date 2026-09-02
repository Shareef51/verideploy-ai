from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from verideploy.rag.retrieval.schemas import RetrievalDocumentKind


class KnowledgeCategory(StrEnum):
    ARCHITECTURE = "architecture"
    RUNBOOK = "runbook"
    POSTMORTEM = "postmortem"
    DEPLOYMENT = "deployment"
    SECURITY = "security"
    DATABASE = "database"
    KUBERNETES = "kubernetes"
    SERVICE = "service"


class RetentionClass(StrEnum):
    OPERATING = "operating"
    AUDIT = "audit"
    HISTORICAL = "historical"


class KnowledgeLineage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: Literal["verideploy-synthetic-corpus"]
    source_record_id: str = Field(min_length=3, max_length=128)
    generator: str = Field(min_length=3, max_length=128)
    generator_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    synthetic: Literal[True] = True
    parent_document_id: UUID | None = None


class KnowledgeDocumentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    path: str = Field(pattern=r"^documents/[a-z0-9][a-z0-9_.-]*\.md$")
    title: str = Field(min_length=3, max_length=200)
    category: KnowledgeCategory
    retrieval_kind: RetrievalDocumentKind
    labels: list[str] = Field(min_length=2, max_length=12)
    service: str | None = Field(default=None, max_length=80)
    environment: str | None = Field(default=None, max_length=40)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_uri: str = Field(pattern=r"^synthetic://verideploy/knowledge/[a-z0-9/_-]+$")
    retention_class: RetentionClass
    lineage: KnowledgeLineage

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().lower() for item in value]
        if any(not item for item in normalized):
            raise ValueError("labels must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("labels must be unique")
        return normalized

    @model_validator(mode="after")
    def category_label_present(self) -> "KnowledgeDocumentManifest":
        if self.category.value not in self.labels:
            raise ValueError("labels must include the document category")
        return self


class KnowledgeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    corpus_name: Literal["verideploy-engineering-knowledge"]
    corpus_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    generated_at: datetime
    tenant_id: UUID
    documents: list[KnowledgeDocumentManifest] = Field(min_length=8)

    @model_validator(mode="after")
    def unique_documents(self) -> "KnowledgeManifest":
        ids = [item.document_id for item in self.documents]
        paths = [item.path for item in self.documents]
        provenance = [item.provenance_uri for item in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document IDs must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("document paths must be unique")
        if len(provenance) != len(set(provenance)):
            raise ValueError("provenance URIs must be unique")
        return self


class RetentionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_class: RetentionClass
    minimum_days: int = Field(ge=30, le=3650)
    immutable: bool
    rationale: str = Field(min_length=10, max_length=500)


class KnowledgeRetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    policy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    rules: list[RetentionRule] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def every_class_has_rule(self) -> "KnowledgeRetentionPolicy":
        classes = [item.retention_class for item in self.rules]
        if set(classes) != set(RetentionClass):
            raise ValueError("retention rules must cover every retention class exactly once")
        if len(classes) != len(set(classes)):
            raise ValueError("retention rules must be unique")
        return self
