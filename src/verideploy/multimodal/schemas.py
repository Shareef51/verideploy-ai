from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Modality(StrEnum):
    DOCUMENT = "document"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class IngestionStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    STORED = "STORED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class IngestionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    tenant_id: UUID
    requested_by: UUID
    correlation_id: UUID
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
    modality: Modality
    original_filename: Annotated[str, Field(min_length=1, max_length=255)]
    detected_mime_type: Annotated[str, Field(min_length=3, max_length=120)]
    size_bytes: Annotated[int, Field(gt=0, le=524_288_000)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    bucket: Annotated[str, Field(min_length=3, max_length=63)]
    object_key: Annotated[str, Field(min_length=3, max_length=1024)]
    object_version: Annotated[str | None, Field(max_length=256)] = None
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def normalize(self) -> "IngestionCommand":
        self.original_filename = self.original_filename.strip().replace("\x00", "")
        if "/" in self.original_filename or "\\" in self.original_filename or self.original_filename in {".", ".."}:
            raise ValueError("original_filename must be a basename")
        return self


class IngestionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID = Field(default_factory=uuid4)
    event_type: Annotated[str, Field(min_length=3, max_length=120)]
    schema_version: str = "1.0"
    tenant_id: UUID
    correlation_id: UUID
    job_id: UUID
    sequence_number: Annotated[int, Field(ge=1)]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    producer: Annotated[str, Field(min_length=2, max_length=100)] = "ingestion-worker"
    trace_context: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class IngestionJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID
    tenant_id: UUID
    requested_by: UUID
    correlation_id: UUID
    idempotency_key: str
    modality: Modality
    original_filename: str
    detected_mime_type: str
    size_bytes: int
    sha256: str
    bucket: str
    object_key: str
    object_version: str | None = None
    status: IngestionStatus
    last_sequence_number: int = 0
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int = 1
