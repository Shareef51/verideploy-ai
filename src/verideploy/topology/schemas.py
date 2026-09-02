from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServiceTier(str, Enum):
    TIER_0 = "tier_0"
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"


class DependencyKind(str, Enum):
    SYNC_HTTP = "sync_http"
    ASYNC_EVENT = "async_event"
    DATA = "data"
    TELEMETRY = "telemetry"


class Criticality(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SLOMetric(str, Enum):
    AVAILABILITY = "availability"
    LATENCY_P95_MS = "latency_p95_ms"
    ERROR_RATE = "error_rate"


class TopologyCompany(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    company_id: UUID
    tenant_id: UUID
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9-]+$")


class TopologyTeam(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    team_id: UUID
    tenant_id: UUID
    company_id: UUID
    name: str
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    mission: str


class TopologyOwner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    owner_id: UUID
    tenant_id: UUID
    team_id: UUID
    display_name: str
    role: str
    oncall_alias: str = Field(pattern=r"^[a-z0-9-]+$")


class TopologyEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    environment_id: UUID
    tenant_id: UUID
    name: str = Field(pattern=r"^(development|staging|production)$")
    region: str
    criticality: Criticality


class TopologyService(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    service_id: UUID
    tenant_id: UUID
    team_id: UUID
    name: str
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    domain: str
    tier: ServiceTier
    runtime: str
    repository: str
    description: str


class TopologyDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dependency_id: UUID
    tenant_id: UUID
    source_service_id: UUID
    target_service_id: UUID
    kind: DependencyKind
    criticality: Criticality
    description: str


class TopologySLO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    slo_id: UUID
    tenant_id: UUID
    service_id: UUID
    environment_id: UUID
    metric: SLOMetric
    target: float = Field(gt=0)
    window_days: int = Field(ge=1, le=90)


class TopologyDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    deployment_id: UUID
    tenant_id: UUID
    service_id: UUID
    environment_id: UUID
    version: str
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    deployed_at: datetime
    cluster: str
    namespace: str
    replicas: int = Field(ge=1, le=1000)


class TopologySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "1.0"
    seed_version: str
    generated_at: datetime
    seed_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    company: TopologyCompany
    teams: list[TopologyTeam]
    owners: list[TopologyOwner]
    environments: list[TopologyEnvironment]
    services: list[TopologyService]
    dependencies: list[TopologyDependency]
    slos: list[TopologySLO]
    deployments: list[TopologyDeployment]

    @model_validator(mode="after")
    def tenant_consistency(self) -> "TopologySnapshot":
        tenant = self.company.tenant_id
        rows = [*self.teams, *self.owners, *self.environments, *self.services, *self.dependencies, *self.slos, *self.deployments]
        if any(row.tenant_id != tenant for row in rows):
            raise ValueError("all topology records must share the company tenant")
        return self


class TopologyValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    valid: bool
    seed_sha256: str
    team_count: int
    owner_count: int
    service_count: int
    dependency_count: int
    environment_count: int
    slo_count: int
    deployment_count: int
    errors: tuple[str, ...] = ()
