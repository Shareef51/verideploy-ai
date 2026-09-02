class MCPGatewayError(RuntimeError):
    code = "mcp_gateway_error"


class MCPToolNotFound(MCPGatewayError):
    code = "mcp_tool_not_found"


class MCPAuthorizationDenied(MCPGatewayError):
    code = "mcp_authorization_denied"


class MCPTenantViolation(MCPGatewayError):
    code = "mcp_tenant_violation"


class MCPInjectionDenied(MCPGatewayError):
    code = "mcp_injection_denied"


class MCPRiskDenied(MCPGatewayError):
    code = "mcp_risk_denied"


class MCPToolTimeout(MCPGatewayError):
    code = "mcp_tool_timeout"


class MCPCircuitOpen(MCPGatewayError):
    code = "mcp_circuit_open"


class MCPToolExecutionFailed(MCPGatewayError):
    code = "mcp_tool_execution_failed"
