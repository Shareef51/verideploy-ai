from __future__ import annotations

from verideploy.mcp.contracts import MCPInvocation


def build_incident_mcp_server(*, gateway, context_factory):
    from mcp.server import MCPServer
    mcp = MCPServer("VeriDeploy-Incident")

    @mcp.tool(name="incident.get")
    async def incident_get(incident_id: str) -> dict:
        ctx = context_factory()
        result = await gateway.invoke(MCPInvocation(tool_name="incident.get", arguments={"incident_id": incident_id}, correlation_id="mcp-sdk:incident.get"), ctx)
        return result.result

    @mcp.tool(name="incident.add_note")
    async def incident_add_note(incident_id: str, note: str, approval_id: str) -> dict:
        ctx = context_factory()
        result = await gateway.invoke(MCPInvocation(tool_name="incident.add_note", arguments={"incident_id": incident_id, "note": note}, correlation_id="mcp-sdk:incident.add_note", approval_id=approval_id), ctx)
        return result.result

    return mcp
