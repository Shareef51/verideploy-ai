from __future__ import annotations

import time
from collections import deque
from collections.abc import AsyncIterator

from verideploy.llm.contracts import AIProviderName, AIRequest, AIResult, AIUsage
from verideploy.llm.errors import AIProviderError
from verideploy.llm.responses import AIResponseStatus, AIStreamEvent, AIStreamEventType


class DeterministicTestProvider:
    def __init__(
        self,
        *,
        output_text: str = "deterministic-test-output",
        failures: list[AIProviderError] | None = None,
    ) -> None:
        self.output_text = output_text
        self.failures = deque(failures or [])
        self.calls = 0
        self.cancelled_response_ids: list[str] = []

    @property
    def name(self) -> str:
        return AIProviderName.TEST.value

    async def execute(self, request: AIRequest) -> AIResult:
        if request.model is None:
            raise ValueError("DeterministicTestProvider requires a resolved model")
        self.calls += 1
        if self.failures:
            raise self.failures.popleft()
        started = time.perf_counter()
        return AIResult(
            request_id=request.request_id,
            provider=AIProviderName.TEST,
            model=request.model,
            output_text=self.output_text,
            response_status=AIResponseStatus.COMPLETED,
            provider_response_id=f"resp-test-{request.request_id}",
            provider_request_id=f"req-test-{request.request_id}",
            usage=AIUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            latency_ms=(time.perf_counter() - started) * 1000,
            attempts=1,
        )

    async def stream(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]:
        result = await self.execute(request)
        yield AIStreamEvent(
            type=AIStreamEventType.RESPONSE_CREATED,
            sequence_number=1,
            request_id=str(request.request_id),
            provider_response_id=result.provider_response_id,
        )
        yield AIStreamEvent(
            type=AIStreamEventType.OUTPUT_TEXT_DELTA,
            sequence_number=2,
            request_id=str(request.request_id),
            provider_response_id=result.provider_response_id,
            delta=self.output_text,
        )
        yield AIStreamEvent(
            type=AIStreamEventType.RESPONSE_COMPLETED,
            sequence_number=3,
            request_id=str(request.request_id),
            provider_response_id=result.provider_response_id,
            final_result=result,
        )

    async def cancel(self, response_id: str) -> bool:
        self.cancelled_response_ids.append(response_id)
        return True
