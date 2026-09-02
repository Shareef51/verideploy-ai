from __future__ import annotations

from verideploy.mcp.contracts import MCPInvocation


def build_monitoring_mcp_server(*, gateway, context_factory):
    from mcp.server import MCPServer
    mcp = MCPServer("VeriDeploy-Monitoring")

    @mcp.tool(name="monitoring.metrics.query")
    async def metrics_query(query: str, start: str, end: str, service: str, environment: str) -> dict:
        ctx = context_factory()
        result = await gateway.invoke(MCPInvocation(tool_name="monitoring.metrics.query", arguments={"query": query, "start": start, "end": end, "service": service, "environment": environment}, correlation_id="mcp-sdk:monitoring.metrics.query"), ctx)
        return result.result

    return mcp
