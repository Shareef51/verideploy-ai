from __future__ import annotations

from .contracts import MCPCallerContext, MCPToolDefinition
from .errors import MCPToolNotFound


class MCPToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, MCPToolDefinition] = {}

    def register(self, tool: MCPToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate MCP tool registration: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> MCPToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise MCPToolNotFound(name) from exc

    def list_for(self, caller: MCPCallerContext) -> list[MCPToolDefinition]:
        return [self._tools[name] for name in sorted(self._tools) if self._tools[name].permission in caller.permissions]

    def by_server(self, server_name: str) -> list[MCPToolDefinition]:
        return [self._tools[name] for name in sorted(self._tools) if self._tools[name].server_name == server_name]
