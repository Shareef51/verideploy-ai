from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

logger = logging.getLogger("verideploy.ai")


@dataclass(frozen=True)
class AITelemetryEvent:
    request_id: UUID
    tenant_id: UUID
    correlation_id: str
    operation: str
    provider: str
    model: str
    model_role: str | None
    attempt: int
    outcome: str
    latency_ms: float
    error_code: str | None = None


class AITelemetry:
    def emit(self, event: AITelemetryEvent) -> None:
        logger.info(
            "ai_request",
            extra={
                "ai_request_id": str(event.request_id),
                "tenant_id": str(event.tenant_id),
                "correlation_id": event.correlation_id,
                "ai_operation": event.operation,
                "ai_provider": event.provider,
                "ai_model": event.model,
                "ai_model_role": event.model_role,
                "ai_attempt": event.attempt,
                "ai_outcome": event.outcome,
                "ai_latency_ms": round(event.latency_ms, 2),
                "ai_error_code": event.error_code,
            },
        )
