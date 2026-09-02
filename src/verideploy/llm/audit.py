from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from verideploy.llm.routing import ModelRole


@dataclass(frozen=True)
class ModelRoutingAuditRecord:
    request_id: UUID
    tenant_id: UUID
    correlation_id: str
    operation: str
    role: ModelRole
    resolved_model: str
    reason: str
    fallback_index: int
    policy_override: bool
    estimated_cost_usd: Decimal
    actual_cost_usd: Decimal | None
    retry_count: int
    latency_ms: float
    outcome: str
    created_at: datetime


class RoutingAuditSink(Protocol):
    async def record(self, record: ModelRoutingAuditRecord) -> None: ...


class InMemoryRoutingAuditSink:
    """Thread-safe deterministic sink for tests/demo. LLMOps Data Platform moves this to the LLMOps database."""

    def __init__(self) -> None:
        self._records: list[ModelRoutingAuditRecord] = []
        self._lock = asyncio.Lock()

    async def record(self, record: ModelRoutingAuditRecord) -> None:
        async with self._lock:
            self._records.append(record)

    async def records(self) -> tuple[ModelRoutingAuditRecord, ...]:
        async with self._lock:
            return tuple(self._records)


def audit_now() -> datetime:
    return datetime.now(UTC)
