from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from verideploy.llm.errors import AIErrorCode, AIProviderError


class RequestController(Protocol):
    async def acquire(self, *, tenant_id: UUID, estimated_cost_usd: Decimal) -> None: ...
    async def settle(self, *, tenant_id: UUID, reserved_cost_usd: Decimal, actual_cost_usd: Decimal) -> None: ...


@dataclass(frozen=True)
class LocalControlPolicy:
    requests_per_minute: int
    monthly_budget_usd: Decimal


class InMemoryRequestController:
    """Deterministic local/test controller; production must use a distributed backend."""

    def __init__(self, policy: LocalControlPolicy) -> None:
        self._policy = policy
        self._requests: dict[UUID, deque[float]] = defaultdict(deque)
        self._spend: dict[UUID, Decimal] = defaultdict(lambda: Decimal("0"))
        self._lock = asyncio.Lock()

    async def acquire(self, *, tenant_id: UUID, estimated_cost_usd: Decimal) -> None:
        now = time.monotonic()
        async with self._lock:
            bucket = self._requests[tenant_id]
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
            if len(bucket) >= self._policy.requests_per_minute:
                raise AIProviderError(
                    "Tenant AI request rate exceeded",
                    code=AIErrorCode.LOCAL_RATE_LIMIT,
                    retryable=True,
                    provider="local-control",
                )
            if self._spend[tenant_id] + estimated_cost_usd > self._policy.monthly_budget_usd:
                raise AIProviderError(
                    "Tenant AI budget exceeded",
                    code=AIErrorCode.BUDGET_EXCEEDED,
                    retryable=False,
                    provider="local-control",
                )
            bucket.append(now)
            self._spend[tenant_id] += max(estimated_cost_usd, Decimal("0"))

    async def settle(self, *, tenant_id: UUID, reserved_cost_usd: Decimal, actual_cost_usd: Decimal) -> None:
        async with self._lock:
            self._spend[tenant_id] += max(actual_cost_usd, Decimal("0")) - max(reserved_cost_usd, Decimal("0"))
            if self._spend[tenant_id] < 0:
                self._spend[tenant_id] = Decimal("0")


class RedisRequestController:
    """Distributed fixed-window RPM and monthly-budget guard using atomic Redis operations."""

    def __init__(self, redis_url: str, *, requests_per_minute: int, monthly_budget_usd: Decimal) -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError("redis package is required for RedisRequestController") from exc
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._rpm = requests_per_minute
        self._budget_microusd = int(monthly_budget_usd * Decimal("1000000"))

    async def acquire(self, *, tenant_id: UUID, estimated_cost_usd: Decimal) -> None:
        now = int(time.time())
        minute = now // 60
        month = time.strftime("%Y%m", time.gmtime(now))
        rate_key = f"verideploy:ai:rpm:{tenant_id}:{minute}"
        budget_key = f"verideploy:ai:budget:{tenant_id}:{month}"
        estimated = int(max(estimated_cost_usd, Decimal("0")) * Decimal("1000000"))
        script = """
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then redis.call('EXPIRE', KEYS[1], 120) end
        if count > tonumber(ARGV[1]) then return {0, 'rate'} end
        local spend = tonumber(redis.call('GET', KEYS[2]) or '0')
        if spend + tonumber(ARGV[2]) > tonumber(ARGV[3]) then return {0, 'budget'} end
        redis.call('INCRBY', KEYS[2], tonumber(ARGV[2]))
        redis.call('EXPIRE', KEYS[2], 3024000)
        return {1, 'ok'}
        """
        result = await self._redis.eval(script, 2, rate_key, budget_key, self._rpm, estimated, self._budget_microusd)
        if int(result[0]) != 1:
            reason = str(result[1])
            raise AIProviderError(
                "Tenant AI request rate exceeded" if reason == "rate" else "Tenant AI budget exceeded",
                code=AIErrorCode.LOCAL_RATE_LIMIT if reason == "rate" else AIErrorCode.BUDGET_EXCEEDED,
                retryable=reason == "rate",
                provider="redis-control",
            )

    async def settle(self, *, tenant_id: UUID, reserved_cost_usd: Decimal, actual_cost_usd: Decimal) -> None:
        now = int(time.time())
        month = time.strftime("%Y%m", time.gmtime(now))
        key = f"verideploy:ai:budget:{tenant_id}:{month}"
        reserved = int(max(reserved_cost_usd, Decimal("0")) * Decimal("1000000"))
        actual = int(max(actual_cost_usd, Decimal("0")) * Decimal("1000000"))
        delta = actual - reserved
        if delta:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incrby(key, delta)
                pipe.expire(key, 35 * 24 * 3600)
                await pipe.execute()
