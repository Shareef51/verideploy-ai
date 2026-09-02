from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from services.ai.mcp_gateway import get_mcp_gateway
from verideploy.mcp.contracts import MCPCallerContext, MCPInvocation, MCPPermission, MCPToolResult
from verideploy.mcp.errors import MCPGatewayError
from verideploy.mcp.gateway import SecureMCPGateway

router = APIRouter(prefix="/internal/v1/mcp", tags=["mcp-internal"])


class MCPInvokePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(min_length=1, max_length=128)
    permissions: list[MCPPermission] = Field(default_factory=list, max_length=32)
    approval_id: str | None = None


def _context(service: str, tenant: UUID, user: str, permissions: list[MCPPermission]) -> MCPCallerContext:
    if service not in {"verideploy-gateway", "verideploy-investigation-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")
    return MCPCallerContext(tenant_id=tenant, user_id=user, service_name=service, permissions=frozenset(permissions))


@router.get("/tools")
async def list_tools(
    permissions: str = "",
    x_internal_service: str = Header(default=""), x_tenant_id: UUID = Header(), x_user_id: str = Header(),
    gateway: SecureMCPGateway = Depends(get_mcp_gateway),
):
    parsed = [MCPPermission(item.strip()) for item in permissions.split(",") if item.strip()]
    caller = _context(x_internal_service, x_tenant_id, x_user_id, parsed)
    return {"tools": gateway.list_tools(caller)}


@router.post("/invoke", response_model=MCPToolResult)
async def invoke(
    payload: MCPInvokePayload,
    x_internal_service: str = Header(default=""), x_tenant_id: UUID = Header(), x_user_id: str = Header(),
    gateway: SecureMCPGateway = Depends(get_mcp_gateway),
) -> MCPToolResult:
    caller = _context(x_internal_service, x_tenant_id, x_user_id, payload.permissions)
    try:
        return await gateway.invoke(MCPInvocation(
            tool_name=payload.tool_name, arguments=payload.arguments, correlation_id=payload.correlation_id,
            approval_id=payload.approval_id,
        ), caller)
    except MCPGatewayError as exc:
        denied = exc.code in {"mcp_authorization_denied", "mcp_tenant_violation", "mcp_injection_denied", "mcp_risk_denied"}
        raise HTTPException(status_code=403 if denied else 502, detail=exc.code) from exc
