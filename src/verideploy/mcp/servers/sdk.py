from __future__ import annotations

from collections.abc import Callable

from ..contracts import MCPCallerContext, MCPInvocation
from ..gateway import SecureMCPGateway


def build_mcp_v2_server(*, server_name: str, gateway: SecureMCPGateway,
                        context_factory: Callable[[], MCPCallerContext]):
    """Build an official MCP Python SDK v2 server lazily.

    The import is intentionally lazy so deterministic unit tests do not require the transport SDK.
    """
    from mcp.server import MCPServer

    server = MCPServer(f"VeriDeploy-{server_name}")
    for definition in gateway.registry.by_server(server_name):
        async def handler(_tool_name: str = definition.name, **arguments):
            context = context_factory()
            result = await gateway.invoke(MCPInvocation(
                tool_name=_tool_name, arguments=arguments,
                correlation_id=f"mcp-sdk:{_tool_name}",
            ), context)
            return result.result

        handler.__name__ = definition.name.replace(".", "_")
        server.tool(name=definition.name)(handler)
    return server
