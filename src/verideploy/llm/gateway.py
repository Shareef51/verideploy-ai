from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from verideploy.llm.audit import ModelRoutingAuditRecord, RoutingAuditSink, audit_now
from verideploy.llm.concurrency import RoleConcurrencyLimiter
from verideploy.llm.contracts import AIRequest, AIResult
from verideploy.llm.controls import RequestController
from verideploy.llm.errors import AIErrorCode, AIProviderError
from verideploy.llm.observability import AITelemetry, AITelemetryEvent
from verideploy.llm.persistence import ResponsePersistence
from verideploy.llm.pricing import CostCalculator
from verideploy.llm.provider import AIProvider
from verideploy.llm.responses import AIResponseStatus, AIStreamEvent, AIStreamEventType
from verideploy.llm.routing import ModelRouter, RoutingDecision
from verideploy.llmops.sinks import ModelCallSink

_FALLBACK_CODES = {
    AIErrorCode.RATE_LIMITED,
    AIErrorCode.PROVIDER_UNAVAILABLE,
    AIErrorCode.TIMEOUT,
    AIErrorCode.CONNECTION,
}
_TERMINAL_STREAM_TYPES = {
    AIStreamEventType.RESPONSE_COMPLETED,
    AIStreamEventType.RESPONSE_INCOMPLETE,
    AIStreamEventType.RESPONSE_CANCELLED,
}


@asynccontextmanager
async def _no_slot():
    yield


class AIGateway:
    def __init__(
        self,
        *,
        provider: AIProvider,
        controller: RequestController,
        router: ModelRouter | None = None,
        cost_calculator: CostCalculator | None = None,
        concurrency_limiter: RoleConcurrencyLimiter | None = None,
        routing_audit: RoutingAuditSink | None = None,
        response_persistence: ResponsePersistence | None = None,
        telemetry: AITelemetry | None = None,
        llmops_sink: ModelCallSink | None = None,
        langsmith_observer: Any | None = None,
        max_attempts: int = 3,
        base_backoff_seconds: float = 0.25,
        max_backoff_seconds: float = 4.0,
    ) -> None:
        if max_attempts < 1 or max_attempts > 8:
            raise ValueError("max_attempts must be between 1 and 8")
        self._provider = provider
        self._controller = controller
        self._router = router
        self._costs = cost_calculator or CostCalculator(None)
        self._concurrency = concurrency_limiter
        self._routing_audit = routing_audit
        self._response_persistence = response_persistence
        self._telemetry = telemetry or AITelemetry()
        self._llmops_sink = llmops_sink
        self._langsmith_observer = langsmith_observer
        self._max_attempts = max_attempts
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds

    async def execute(self, request: AIRequest, *, estimated_cost_usd: Decimal | None = None) -> AIResult:
        decision = self._resolve_route(request)
        last_error: AIProviderError | None = None
        for fallback_index, model in enumerate(decision.ordered_models):
            routed_request = request.model_copy(update={"model": model, "model_role": decision.role})
            estimate = self._costs.estimate(
                model=model, input_text=self._input_text(routed_request), max_output_tokens=routed_request.max_output_tokens
            )
            reservation = estimated_cost_usd if estimated_cost_usd is not None else estimate.estimated_cost_usd
            if not estimate.priced and estimated_cost_usd is None:
                reservation = Decimal("0")
            await self._controller.acquire(tenant_id=request.tenant_id, estimated_cost_usd=reservation)
            started_model = time.perf_counter()
            try:
                result, attempts = await self._execute_model(routed_request)
                enriched, actual_cost = await self._finalize_success(
                    request=request,
                    routed_request=routed_request,
                    result=result,
                    decision=decision,
                    model=model,
                    fallback_index=fallback_index,
                    attempts=attempts,
                    reservation=reservation,
                    estimated_cost=estimate.estimated_cost_usd if estimate.priced else reservation,
                    started_model=started_model,
                )
                return enriched
            except asyncio.CancelledError:
                await self._controller.settle(
                    tenant_id=request.tenant_id, reserved_cost_usd=reservation, actual_cost_usd=Decimal("0")
                )
                raise
            except AIProviderError as exc:
                last_error = exc
                await self._controller.settle(
                    tenant_id=request.tenant_id, reserved_cost_usd=reservation, actual_cost_usd=Decimal("0")
                )
                await self._audit(
                    request=request,
                    decision=decision,
                    model=model,
                    fallback_index=fallback_index,
                    estimated_cost=estimate.estimated_cost_usd if estimate.priced else reservation,
                    actual_cost=None,
                    retry_count=self._max_attempts - 1 if exc.retryable else 0,
                    latency_ms=(time.perf_counter() - started_model) * 1000,
                    outcome=f"error:{exc.code.value}",
                )
                if self._llmops_sink is not None:
                    await self._llmops_sink.failure(request=request, model=model, role=decision.role.value, retry_count=self._max_attempts - 1 if exc.retryable else 0, latency_ms=(time.perf_counter() - started_model) * 1000, error_code=exc.code.value)
                await self._observe_langsmith_failure(
                    request=request, model=model, role=decision.role.value,
                    retry_count=self._max_attempts - 1 if exc.retryable else 0,
                    latency_ms=(time.perf_counter() - started_model) * 1000, error_code=exc.code.value,
                )
                if exc.code not in _FALLBACK_CODES or fallback_index >= len(decision.fallback_models):
                    raise
        assert last_error is not None
        raise last_error

    async def stream(self, request: AIRequest, *, estimated_cost_usd: Decimal | None = None) -> AsyncIterator[AIStreamEvent]:
        """Stream one normalized contract. Retry/fallback is allowed only before visible output."""
        decision = self._resolve_route(request)
        last_error: AIProviderError | None = None
        for fallback_index, model in enumerate(decision.ordered_models):
            routed_request = request.model_copy(update={"model": model, "model_role": decision.role})
            estimate = self._costs.estimate(
                model=model, input_text=self._input_text(routed_request), max_output_tokens=routed_request.max_output_tokens
            )
            reservation = estimated_cost_usd if estimated_cost_usd is not None else estimate.estimated_cost_usd
            if not estimate.priced and estimated_cost_usd is None:
                reservation = Decimal("0")
            await self._controller.acquire(tenant_id=request.tenant_id, estimated_cost_usd=reservation)
            started_model = time.perf_counter()
            slot = self._concurrency.slot(decision.role) if self._concurrency else _no_slot()
            async with slot:
                emitted_visible = False
                for attempt in range(1, self._max_attempts + 1):
                    try:
                        terminal: AIStreamEvent | None = None
                        async for event in self._provider.stream(routed_request):
                            if event.type in _TERMINAL_STREAM_TYPES:
                                terminal = event
                                continue
                            emitted_visible = True
                            yield event
                        if terminal is None or not isinstance(terminal.final_result, AIResult):
                            raise AIProviderError(
                                "provider stream ended without typed final result",
                                code=AIErrorCode.CONNECTION,
                                retryable=not emitted_visible,
                                provider=self._provider.name,
                            )
                        enriched, _ = await self._finalize_success(
                            request=request,
                            routed_request=routed_request,
                            result=terminal.final_result,
                            decision=decision,
                            model=model,
                            fallback_index=fallback_index,
                            attempts=attempt,
                            reservation=reservation,
                            estimated_cost=estimate.estimated_cost_usd if estimate.priced else reservation,
                            started_model=started_model,
                        )
                        terminal_type = (
                            AIStreamEventType.RESPONSE_COMPLETED
                            if enriched.response_status is AIResponseStatus.COMPLETED
                            else AIStreamEventType.RESPONSE_INCOMPLETE
                        )
                        yield terminal.model_copy(update={"type": terminal_type, "final_result": enriched})
                        return
                    except asyncio.CancelledError:
                        await self._controller.settle(
                            tenant_id=request.tenant_id,
                            reserved_cost_usd=reservation,
                            actual_cost_usd=reservation if emitted_visible else Decimal("0"),
                        )
                        self._emit(request, attempt, "cancelled", (time.perf_counter() - started_model) * 1000, "cancelled")
                        raise
                    except AIProviderError as exc:
                        last_error = exc
                        self._emit(request, attempt, "error", (time.perf_counter() - started_model) * 1000, exc.code.value)
                        if emitted_visible:
                            await self._controller.settle(
                                tenant_id=request.tenant_id,
                                reserved_cost_usd=reservation,
                                actual_cost_usd=reservation,
                            )
                            await self._audit(
                                request=request,
                                decision=decision,
                                model=model,
                                fallback_index=fallback_index,
                                estimated_cost=estimate.estimated_cost_usd if estimate.priced else reservation,
                                actual_cost=reservation,
                                retry_count=max(0, attempt - 1),
                                latency_ms=(time.perf_counter() - started_model) * 1000,
                                outcome=f"partial_stream_error:{exc.code.value}",
                            )
                            raise
                        if exc.retryable and attempt < self._max_attempts:
                            await asyncio.sleep(self._backoff(attempt, exc.retry_after_seconds))
                            continue
                        await self._controller.settle(
                            tenant_id=request.tenant_id,
                            reserved_cost_usd=reservation,
                            actual_cost_usd=Decimal("0"),
                        )
                        await self._audit(
                            request=request,
                            decision=decision,
                            model=model,
                            fallback_index=fallback_index,
                            estimated_cost=estimate.estimated_cost_usd if estimate.priced else reservation,
                            actual_cost=None,
                            retry_count=max(0, attempt - 1),
                            latency_ms=(time.perf_counter() - started_model) * 1000,
                            outcome=f"error:{exc.code.value}",
                        )
                        break
            if last_error is None or last_error.code not in _FALLBACK_CODES or fallback_index >= len(decision.fallback_models):
                if last_error is not None:
                    raise last_error
        assert last_error is not None
        raise last_error

    async def cancel(self, response_id: str) -> bool:
        return await self._provider.cancel(response_id)

    async def get_persisted_response(self, *, tenant_id, provider_response_id: str) -> AIResult | None:
        if self._response_persistence is None:
            return None
        return await self._response_persistence.get(
            tenant_id=tenant_id, provider_response_id=provider_response_id
        )

    @staticmethod
    def _input_text(request: AIRequest) -> str:
        if isinstance(request.input, str):
            return request.input
        # Never feed base64 image bytes into text-token estimation/log-like accounting.
        # Provider-reported usage is authoritative for actual multimodal cost settlement.
        normalized: list[dict[str, object]] = []
        for item in request.input:
            dumped = item.model_dump(mode="json", exclude_none=True)
            content = dumped.get("content")
            if isinstance(content, list):
                safe_parts: list[dict[str, object]] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "input_image":
                        safe_parts.append({"type": "input_image", "detail": part.get("detail", "auto")})
                    else:
                        safe_parts.append(part)
                dumped["content"] = safe_parts
            normalized.append(dumped)
        return json.dumps(normalized, sort_keys=True)


    async def persist_validated_response(self, *, request: AIRequest, result: AIResult) -> None:
        """Persist only after an outer validation boundary has accepted the result."""
        if self._response_persistence is not None:
            await self._response_persistence.save(tenant_id=request.tenant_id, request=request, result=result)

    async def _finalize_success(
        self,
        *,
        request: AIRequest,
        routed_request: AIRequest,
        result: AIResult,
        decision: RoutingDecision,
        model: str,
        fallback_index: int,
        attempts: int,
        reservation: Decimal,
        estimated_cost: Decimal,
        started_model: float,
    ) -> tuple[AIResult, Decimal | None]:
        actual = self._costs.actual(model=model, usage=result.usage)
        settlement = actual.actual_cost_usd if actual.actual_cost_usd is not None else reservation
        await self._controller.settle(
            tenant_id=request.tenant_id,
            reserved_cost_usd=reservation,
            actual_cost_usd=settlement,
        )
        latency = (time.perf_counter() - started_model) * 1000
        enriched = result.model_copy(
            update={
                "model_role": decision.role,
                "model": model,
                "route_reason": decision.reason,
                "estimated_cost_usd": str(estimated_cost),
                "actual_cost_usd": str(actual.actual_cost_usd) if actual.actual_cost_usd is not None else None,
                "attempts": attempts,
                "fallback_index": fallback_index,
            }
        )
        if self._response_persistence is not None and not routed_request.defer_response_persistence:
            await self._response_persistence.save(tenant_id=request.tenant_id, request=routed_request, result=enriched)
        await self._audit(
            request=request,
            decision=decision,
            model=model,
            fallback_index=fallback_index,
            estimated_cost=estimated_cost,
            actual_cost=actual.actual_cost_usd,
            retry_count=max(0, attempts - 1),
            latency_ms=latency,
            outcome="success",
        )
        if self._llmops_sink is not None:
            await self._llmops_sink.success(request=request, result=enriched, latency_ms=latency)
        await self._observe_langsmith_success(request=request, result=enriched, latency_ms=latency)
        return enriched, actual.actual_cost_usd

    async def _observe_langsmith_success(self, *, request: AIRequest, result: AIResult, latency_ms: float) -> None:
        if self._langsmith_observer is None:
            return
        try:
            await self._langsmith_observer.model_success(request=request, result=result, latency_ms=latency_ms)
        except Exception:
            # External observability must never alter a business result.
            return

    async def _observe_langsmith_failure(
        self, *, request: AIRequest, model: str, role: str, retry_count: int, latency_ms: float, error_code: str
    ) -> None:
        if self._langsmith_observer is None:
            return
        try:
            await self._langsmith_observer.model_failure(
                request=request, model=model, role=role, retry_count=retry_count,
                latency_ms=latency_ms, error_code=error_code
            )
        except Exception:
            return

    async def _execute_model(self, request: AIRequest) -> tuple[AIResult, int]:
        role = request.model_role
        if role is None:
            raise RuntimeError("routed request is missing model role")
        if self._concurrency is None:
            return await self._execute_attempts(request)
        async with self._concurrency.slot(role):
            return await self._execute_attempts(request)

    async def _execute_attempts(self, request: AIRequest) -> tuple[AIResult, int]:
        last_error: AIProviderError | None = None
        for attempt in range(1, self._max_attempts + 1):
            started = time.perf_counter()
            try:
                result = await self._provider.execute(request)
                result.attempts = attempt
                self._emit(request, attempt, "success", (time.perf_counter() - started) * 1000)
                return result, attempt
            except asyncio.CancelledError:
                self._emit(request, attempt, "cancelled", (time.perf_counter() - started) * 1000, "cancelled")
                raise
            except AIProviderError as exc:
                last_error = exc
                self._emit(request, attempt, "error", (time.perf_counter() - started) * 1000, exc.code.value)
                if not exc.retryable or attempt >= self._max_attempts:
                    raise
                await asyncio.sleep(self._backoff(attempt, exc.retry_after_seconds))
        assert last_error is not None
        raise last_error

    def _resolve_route(self, request: AIRequest) -> RoutingDecision:
        if self._router is None:
            if request.model is None:
                raise ValueError("AI request requires either configured ModelRouter or explicit model")
            from verideploy.llm.routing import ModelRole

            return RoutingDecision(
                role=request.model_role or ModelRole.STANDARD,
                primary_model=request.model,
                fallback_models=(),
                reason="legacy_explicit_model",
                policy_override=True,
            )
        return self._router.route(
            operation=request.operation,
            requested_role=request.model_role,
            explicit_model=request.model,
        )

    async def _audit(
        self,
        *,
        request: AIRequest,
        decision: RoutingDecision,
        model: str,
        fallback_index: int,
        estimated_cost: Decimal,
        actual_cost: Decimal | None,
        retry_count: int,
        latency_ms: float,
        outcome: str,
    ) -> None:
        if self._routing_audit is None:
            return
        await self._routing_audit.record(
            ModelRoutingAuditRecord(
                request_id=request.request_id,
                tenant_id=request.tenant_id,
                correlation_id=request.correlation_id,
                operation=request.operation,
                role=decision.role,
                resolved_model=model,
                reason=decision.reason,
                fallback_index=fallback_index,
                policy_override=decision.policy_override,
                estimated_cost_usd=estimated_cost,
                actual_cost_usd=actual_cost,
                retry_count=retry_count,
                latency_ms=latency_ms,
                outcome=outcome,
                created_at=audit_now(),
            )
        )

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(max(retry_after, 0.0), self._max_backoff)
        exponential = min(self._base_backoff * (2 ** (attempt - 1)), self._max_backoff)
        return exponential * random.uniform(0.75, 1.25)

    def _emit(self, request: AIRequest, attempt: int, outcome: str, latency_ms: float, error_code: str | None = None) -> None:
        self._telemetry.emit(
            AITelemetryEvent(
                request_id=request.request_id,
                tenant_id=request.tenant_id,
                correlation_id=request.correlation_id,
                operation=request.operation,
                provider=self._provider.name,
                model=request.model or "unresolved",
                model_role=request.model_role.value if request.model_role is not None else None,
                attempt=attempt,
                outcome=outcome,
                latency_ms=latency_ms,
                error_code=error_code,
            )
        )
