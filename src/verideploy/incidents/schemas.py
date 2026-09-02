from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IncidentSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class FailureMode(str, Enum):
    DB_POOL_EXHAUSTION = "db_pool_exhaustion"
    INCOMPATIBLE_SCHEMA_MIGRATION = "incompatible_schema_migration"
    TLS_CERTIFICATE_EXPIRY = "tls_certificate_expiry"
    CACHE_MEMORY_PRESSURE = "cache_memory_pressure"
    CONSUMER_LAG = "consumer_lag"
    DOWNSTREAM_TIMEOUT = "downstream_timeout"
    CPU_SATURATION = "cpu_saturation"
    BAD_CONFIGURATION = "bad_configuration"


class IncidentSeverity(str, Enum):
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"


class ReleaseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    deployment_id: UUID
    version: str
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    deployed_at: datetime
    causally_related: bool


class MetricPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    metric: str
    timestamp: datetime
    value: float
    unit: str
    causal: bool


class LogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    log_id: UUID
    timestamp: datetime
    level: Literal["INFO", "WARN", "ERROR"]
    service_id: UUID
    message: str
    causal: bool


class TraceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trace_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    span_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    timestamp: datetime
    service_id: UUID
    operation: str
    duration_ms: float = Field(ge=0)
    status: Literal["OK", "ERROR"]
    causal: bool


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: UUID
    timestamp: datetime
    kind: Literal["release", "signal", "impact", "mitigation", "resolution"]
    summary: str
    causal: bool


class IncidentResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resolved_at: datetime
    action: str
    verification: str


class SyntheticIncident(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1.0"
    incident_id: UUID
    family_id: UUID
    tenant_id: UUID
    split: IncidentSplit
    failure_mode: FailureMode
    severity: IncidentSeverity
    primary_service_id: UUID
    environment_id: UUID
    started_at: datetime
    detected_at: datetime
    resolved_at: datetime
    release: ReleaseEvidence
    metrics: tuple[MetricPoint, ...]
    logs: tuple[LogRecord, ...]
    traces: tuple[TraceSpan, ...]
    timeline: tuple[TimelineEvent, ...]
    resolution: IncidentResolution
    root_cause_summary: str
    trigger_summary: str
    incident_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def time_order(self) -> "SyntheticIncident":
        if not (self.started_at <= self.detected_at <= self.resolved_at):
            raise ValueError("incident timestamps must be ordered")
        if self.resolution.resolved_at != self.resolved_at:
            raise ValueError("resolution timestamp must equal incident resolved_at")
        return self


class IncidentDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1.0"
    seed_version: str
    seed: int
    generated_at: datetime
    topology_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    incidents: tuple[SyntheticIncident, ...]


class IncidentDatasetValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    valid: bool
    dataset_sha256: str
    incident_count: int
    label_counts: dict[str, int]
    split_counts: dict[str, int]
    errors: tuple[str, ...] = ()
