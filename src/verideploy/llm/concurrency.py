from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from verideploy.llm.routing import ModelRole


class RoleConcurrencyLimiter:
    """Per-process role limiter; distributed request admission remains owned by RequestController."""

    def __init__(self, limits: Mapping[ModelRole, int]) -> None:
        normalized: dict[ModelRole, int] = {}
        for role in ModelRole:
            value = int(limits.get(role, 1))
            if value < 1:
                raise ValueError(f"concurrency limit for {role.value} must be >= 1")
            normalized[role] = value
        self._semaphores = {role: asyncio.Semaphore(value) for role, value in normalized.items()}

    @asynccontextmanager
    async def slot(self, role: ModelRole) -> AsyncIterator[None]:
        semaphore = self._semaphores[role]
        await semaphore.acquire()
        try:
            yield
        finally:
            semaphore.release()
