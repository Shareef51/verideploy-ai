from __future__ import annotations

import asyncio
import hashlib
import json
import time
from uuid import uuid4

from pydantic import ValidationError

from ..circuit_breaker import ToolCircuitBreaker
from ..contracts import (
    MCPAuditRecord, MCPCallerContext, MCPDecision, MCPInvocation, MCPRisk,
    MCPToolEffect, MCPToolResult,
)
from ..errors import (
    MCPAuthorizationDenied, MCPGatewayError, MCPRiskDenied, MCPToolExecutionFailed,
    MCPToolTimeout,
)
from ..registry import MCPToolRegistry
from ..repository import MCPAuditRepository
from ..security import enforce_tenant_scope, reject_injected_arguments, sanitize_output
from verideploy.observability.telemetry import traced_async


class SecureMCPGateway:
    def __init__(self, *, registry: MCPToolRegistry, audit: MCPAuditRepository,
                 external_writes_enabled: bool = False, breaker_threshold: int = 3,
                 breaker_reset_seconds: float = 30.0) -> None:
        self.registry = registry
        self.audit = audit
        self.external_writes_enabled = external_writes_enabled
        self.breaker = ToolCircuitBreaker(threshold=breaker_threshold, reset_seconds=breaker_reset_seconds)

    def list_tools(self, caller: MCPCallerContext) -> list[dict[str, object]]:
        visible = [tool for tool in self.registry.list_for(caller)
                   if self.external_writes_enabled or tool.effect != MCPToolEffect.WRITE]
        return [{
            "name": tool.name, "server_name": tool.server_name,
            "description": tool.description, "permission": tool.permission,
            "risk": tool.risk, "effect": tool.effect,
            "input_schema": tool.input_model.model_json_schema(),
            "output_schema": tool.output_model.model_json_schema(),
        } for tool in visible]

    @traced_async("mcp.invoke")
    async def invoke(self, invocation: MCPInvocation, caller: MCPCallerContext) -> MCPToolResult:
        started = time.perf_counter()
        invocation_id = uuid4()
        tool = self.registry.get(invocation.tool_name)
        args_hash = self._hash_args(invocation.arguments)
        decision = MCPDecision.FAILED
        error_code: str | None = None
        try:
            if tool.permission not in caller.permissions:
                raise MCPAuthorizationDenied("caller lacks MCP tool permission")
            reject_injected_arguments(invocation.arguments)
            scoped = enforce_tenant_scope(invocation.arguments, caller.tenant_id)
            if tool.effect == MCPToolEffect.WRITE:
                if not self.external_writes_enabled:
                    raise MCPRiskDenied("external MCP writes are disabled")
                if tool.risk in {MCPRisk.HIGH, MCPRisk.CRITICAL} and not invocation.approval_id:
                    raise MCPRiskDenied("high-risk MCP write requires approval")
            validated = tool.input_model.model_validate(scoped).model_dump(mode="json")
            self.breaker.before_call(tool.name)
            try:
                raw = await asyncio.wait_for(tool.handler(validated, caller), timeout=tool.timeout_seconds)
            except TimeoutError as exc:
                self.breaker.failure(tool.name)
                raise MCPToolTimeout(tool.name) from exc
            except MCPGatewayError:
                self.breaker.failure(tool.name)
                raise
            except Exception as exc:
                self.breaker.failure(tool.name)
                raise MCPToolExecutionFailed(tool.name) from exc
            sanitized = sanitize_output(raw)
            try:
                output = tool.output_model.model_validate(sanitized).model_dump(mode="json")
            except ValidationError as exc:
                self.breaker.failure(tool.name)
                raise MCPToolExecutionFailed("invalid tool output schema") from exc
            self.breaker.success(tool.name)
            decision = MCPDecision.ALLOWED
            return MCPToolResult(
                invocation_id=invocation_id, tool_name=tool.name, server_name=tool.server_name,
                result=output, provenance={"tool": tool.name, "server": tool.server_name},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except MCPGatewayError as exc:
            decision = MCPDecision.DENIED if exc.code in {
                "mcp_authorization_denied", "mcp_tenant_violation", "mcp_injection_denied", "mcp_risk_denied"
            } else MCPDecision.FAILED
            error_code = exc.code
            raise
        finally:
            self.audit.append(MCPAuditRecord(
                invocation_id=invocation_id, tenant_id=caller.tenant_id, user_id=caller.user_id,
                service_name=caller.service_name, tool_name=tool.name, server_name=tool.server_name,
                permission=tool.permission, risk=tool.risk, effect=tool.effect, decision=decision,
                correlation_id=invocation.correlation_id, arguments_sha256=args_hash,
                approval_id=invocation.approval_id, error_code=error_code,
                duration_ms=(time.perf_counter() - started) * 1000,
            ))

    @staticmethod
    def _hash_args(arguments: dict[str, object]) -> str:
        raw = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(raw).hexdigest()
