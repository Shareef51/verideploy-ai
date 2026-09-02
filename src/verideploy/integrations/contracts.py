from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class IntegrationType(StrEnum):
    GITHUB="github"; JIRA="jira"; PROMETHEUS="prometheus"; GRAFANA="grafana"; TRACE="trace"; LOG="log"
class IntegrationStatus(StrEnum):
    OK="ok"; DEGRADED="degraded"; UNCONFIGURED="unconfigured"; FAILED="failed"

class IntegrationRecord(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source: IntegrationType
    source_id: str
    observed_at: datetime | None = None
    data: dict[str, Any] = Field(default_factory=dict)

class IntegrationResult(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source: IntegrationType
    status: IntegrationStatus
    records: list[IntegrationRecord] = Field(default_factory=list)
    pages_fetched: int = 0
    requests_made: int = 0
    error_code: str | None = None
    configured: bool = True
