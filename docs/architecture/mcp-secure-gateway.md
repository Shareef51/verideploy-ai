# MCP Servers and Secure Gateway

MCP Secure Gateway introduces the MCP security/control plane. Four logical MCP servers are exposed: GitHub, monitoring, knowledge, and incident. Every tool is registered in one deterministic `MCPToolRegistry` with a Pydantic input/output schema, permission, risk, read/write effect, timeout, and handler.

## Security boundary

The language model never authorizes itself. A trusted `MCPCallerContext` supplies tenant, user, internal service identity, and granted permissions. `SecureMCPGateway` validates authorization, injects tenant scope, rejects tenant overrides and instruction-like prompt-injection arguments, enforces default-disabled external writes and explicit approval for high-risk writes, then executes under timeout/circuit-breaker control. Results are sanitized and validated again before release.

## MCP SDK

The project targets the current official MCP Python SDK v2 (`mcp>=2,<3`) and exposes server builders using `mcp.server.MCPServer`. SDK imports are lazy so tests can exercise the security gateway without requiring a transport runtime. Real Engineering Data Integrations owns production-grade integration hardening such as pagination, quotas, host allowlists, and external-system parity.

## Registered tools

- `github.repository.get` — low-risk read
- `github.pull_request.get` — low-risk read
- `monitoring.metrics.query` — medium-risk read
- `knowledge.search` — low-risk read
- `incident.get` — low-risk read
- `incident.add_note` — high-risk write; disabled by default and approval-gated when writes are enabled

## Audit

Every resolved invocation is recorded in `mcp_tool_audit`, including denied and failed calls. The journal stores tenant/user/service/tool, permission/risk/effect/decision, correlation ID, argument SHA-256, approval reference, sanitized error code, and duration. Raw tool arguments are not persisted by this audit table. Forced PostgreSQL RLS provides defense-in-depth tenant isolation.
