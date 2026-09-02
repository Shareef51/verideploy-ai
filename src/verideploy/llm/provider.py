from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from verideploy.llm.contracts import AIRequest, AIResult
from verideploy.llm.responses import AIStreamEvent


class AIProvider(Protocol):
    @property
    def name(self) -> str: ...
    async def execute(self, request: AIRequest) -> AIResult: ...
    def stream(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]: ...
    async def cancel(self, response_id: str) -> bool: ...
