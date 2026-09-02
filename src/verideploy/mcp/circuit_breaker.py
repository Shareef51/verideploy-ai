from __future__ import annotations

import time
from dataclasses import dataclass

from .errors import MCPCircuitOpen


@dataclass
class _State:
    failures: int = 0
    open_until: float = 0.0


class ToolCircuitBreaker:
    def __init__(self, *, threshold: int = 3, reset_seconds: float = 30.0) -> None:
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self._states: dict[str, _State] = {}

    def before_call(self, tool_name: str) -> None:
        state = self._states.get(tool_name)
        if state and state.open_until > time.monotonic():
            raise MCPCircuitOpen(tool_name)
        if state and state.open_until:
            state.failures = 0
            state.open_until = 0.0

    def success(self, tool_name: str) -> None:
        self._states.pop(tool_name, None)

    def failure(self, tool_name: str) -> None:
        state = self._states.setdefault(tool_name, _State())
        state.failures += 1
        if state.failures >= self.threshold:
            state.open_until = time.monotonic() + self.reset_seconds
