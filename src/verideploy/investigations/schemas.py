from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InvestigationStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WorkflowType(StrEnum):
    INCIDENT_INVESTIGATION = "incident_investigation"


class CreateInvestigationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investigation_id: UUID
    tenant_id: UUID
    requested_by: UUID
    correlation_id: UUID = Field(default_factory=uuid4)
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
    query: Annotated[str, Field(min_length=10, max_length=8_000)]
    workflow_type: WorkflowType = WorkflowType.INCIDENT_INVESTIGATION
    incident_id: Annotated[str | None, Field(max_length=120)] = None
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def normalize(self) -> "CreateInvestigationCommand":
        self.query = " ".join(self.query.split())
        self.incident_id = self.incident_id.strip() if self.incident_id else None
        return self


class CancelInvestigationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investigation_id: UUID
    tenant_id: UUID
    requested_by: UUID
    correlation_id: UUID
    reason: Annotated[str, Field(min_length=3, max_length=500)]
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InvestigationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    event_type: Annotated[str, Field(min_length=3, max_length=120)]
    schema_version: str = "1.0"
    tenant_id: UUID
    correlation_id: UUID
    investigation_id: UUID
    sequence_number: Annotated[int, Field(ge=1)]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    producer: Annotated[str, Field(min_length=2, max_length=100)]
    trace_context: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class InvestigationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investigation_id: UUID
    tenant_id: UUID
    requested_by: UUID
    correlation_id: UUID
    idempotency_key: str
    query: str
    workflow_type: WorkflowType
    incident_id: str | None
    status: InvestigationStatus
    cancel_requested: bool = False
    cancel_reason: str | None = None
    last_sequence_number: int = 0
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int = 1


class InvestigationList(BaseModel):
    items: list[InvestigationRecord]
    next_cursor: str | None = None
