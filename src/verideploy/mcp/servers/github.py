from __future__ import annotations

from verideploy.mcp.contracts import MCPInvocation


def build_github_mcp_server(*, gateway, context_factory):
    from mcp.server import MCPServer
    mcp = MCPServer("VeriDeploy-GitHub")

    @mcp.tool(name="github.repository.get")
    async def repository_get(owner: str, repo: str) -> dict:
        ctx = context_factory()
        result = await gateway.invoke(MCPInvocation(tool_name="github.repository.get", arguments={"owner": owner, "repo": repo}, correlation_id="mcp-sdk:github.repository.get"), ctx)
        return result.result

    @mcp.tool(name="github.pull_request.get")
    async def pull_request_get(owner: str, repo: str, number: int) -> dict:
        ctx = context_factory()
        result = await gateway.invoke(MCPInvocation(tool_name="github.pull_request.get", arguments={"owner": owner, "repo": repo, "number": number}, correlation_id="mcp-sdk:github.pull_request.get"), ctx)
        return result.result

    return mcp
