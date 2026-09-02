from __future__ import annotations

from verideploy.mcp.contracts import MCPInvocation


def build_knowledge_mcp_server(*, gateway, context_factory):
    from mcp.server import MCPServer
    mcp = MCPServer("VeriDeploy-Knowledge")

    @mcp.tool(name="knowledge.search")
    async def knowledge_search(query: str, top_k: int = 5) -> dict:
        ctx = context_factory()
        result = await gateway.invoke(MCPInvocation(tool_name="knowledge.search", arguments={"query": query, "top_k": top_k}, correlation_id="mcp-sdk:knowledge.search"), ctx)
        return result.result

    return mcp
