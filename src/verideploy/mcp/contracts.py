from __future__ import annotations

from enum import StrEnum
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class MCPRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MCPToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"


class MCPPermission(StrEnum):
    GITHUB_READ = "mcp.github.read"
    MONITORING_READ = "mcp.monitoring.read"
    KNOWLEDGE_READ = "mcp.knowledge.read"
    INCIDENT_READ = "mcp.incident.read"
    INCIDENT_WRITE = "mcp.incident.write"


class MCPDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    FAILED = "failed"


class MCPCallerContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    user_id: str = Field(min_length=1, max_length=160)
    service_name: str = Field(min_length=1, max_length=120)
    permissions: frozenset[MCPPermission] = Field(default_factory=frozenset)


class MCPInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=3, max_length=160)
    arguments: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(min_length=1, max_length=128)
    approval_id: str | None = Field(default=None, max_length=160)


class MCPToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation_id: UUID = Field(default_factory=uuid4)
    tool_name: str
    server_name: str
    result: dict[str, Any]
    provenance: dict[str, str] = Field(default_factory=dict)
    duration_ms: float = Field(ge=0)


class MCPAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audit_id: UUID = Field(default_factory=uuid4)
    invocation_id: UUID
    tenant_id: UUID
    user_id: str
    service_name: str
    tool_name: str
    server_name: str
    permission: MCPPermission
    risk: MCPRisk
    effect: MCPToolEffect
    decision: MCPDecision
    correlation_id: str
    arguments_sha256: str
    approval_id: str | None = None
    error_code: str | None = None
    duration_ms: float = Field(ge=0)


ToolHandler = Callable[[dict[str, Any], MCPCallerContext], Awaitable[dict[str, Any]]]


class MCPToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,159}$")
    server_name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    description: str = Field(min_length=1, max_length=2000)
    permission: MCPPermission
    risk: MCPRisk
    effect: MCPToolEffect
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    timeout_seconds: float = Field(default=15.0, gt=0, le=120)
