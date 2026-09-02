from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class EmbeddingState(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    REEMBEDDING = "REEMBEDDING"
    FAILED = "FAILED"


class EmbeddingInput(BaseModel):
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    text: str = Field(min_length=1, max_length=2_000_000)

    @field_validator("text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("embedding text must not be blank")
        return value


class EmbeddingRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: str = Field(min_length=1, max_length=128)
    inputs: list[EmbeddingInput] = Field(min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    dimensions: int | None = Field(default=None, ge=1, le=65536)


class EmbeddingUsage(BaseModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class EmbeddingVector(BaseModel):
    index: int = Field(ge=0)
    values: list[float] = Field(min_length=1)


class EmbeddingProviderResult(BaseModel):
    provider_request_id: str | None = None
    model: str
    vectors: list[EmbeddingVector]
    usage: EmbeddingUsage = Field(default_factory=EmbeddingUsage)


class EmbeddingRecord(BaseModel):
    embedding_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str
    dimensions: int = Field(ge=1)
    registry_version: int = Field(ge=1)
    values: list[float] = Field(min_length=1)
    state: EmbeddingState = EmbeddingState.CURRENT
    provider_request_id: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EmbeddingBatchResult(BaseModel):
    request_id: UUID
    tenant_id: UUID
    model: str
    dimensions: int
    records: list[EmbeddingRecord]
    cache_hits: int = Field(ge=0)
    provider_input_count: int = Field(ge=0)
    provider_prompt_tokens: int | None = Field(default=None, ge=0)
    provider_request_ids: list[str] = Field(default_factory=list)


class EmbeddingModelSpec(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    dimensions: int = Field(ge=1, le=65536)
    provider: str = Field(default="openai", min_length=1, max_length=64)
    registry_version: int = Field(default=1, ge=1)
    enabled: bool = True
    supports_dimensions_override: bool = True


class ReembeddingPlan(BaseModel):
    tenant_id: UUID
    from_model: str
    from_dimensions: int
    to_model: str
    to_dimensions: int
    stale_records: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


EmbeddingValues = Annotated[list[float], Field(min_length=1)]
