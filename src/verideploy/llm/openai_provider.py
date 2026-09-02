from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from verideploy.llm.contracts import AIProviderName, AIRequest, AIResult, AIUsage
from verideploy.llm.errors import AIErrorCode, AIProviderError
from verideploy.llm.responses import (
    AIFunctionToolChoice,
    AIResponseStatus,
    AIStreamEvent,
    AIStreamEventType,
    AIToolCall,
)


class OpenAIProvider:
    """Production OpenAI Responses API adapter with normalized streaming and errors."""

    def __init__(self, *, api_key: str, timeout_seconds: float, client: Any | None = None) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI provider")
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise RuntimeError("official openai package is required for OpenAIProvider") from exc
            # VeriDeploy owns application retries so every attempt is visible and auditable.
            client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)
        self._client = client

    @property
    def name(self) -> str:
        return AIProviderName.OPENAI.value

    async def execute(self, request: AIRequest) -> AIResult:
        if request.model is None:
            raise ValueError("OpenAIProvider requires a resolved model")
        started = time.perf_counter()
        try:
            response = await self._client.responses.create(**self._create_kwargs(request, stream=False))
        except Exception as exc:
            raise self._classify_exception(exc) from exc
        return self._normalize_response(request, response, elapsed_ms=(time.perf_counter() - started) * 1000)

    async def stream(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]:
        if request.model is None:
            raise ValueError("OpenAIProvider requires a resolved model")
        started = time.perf_counter()
        provider_response_id: str | None = None
        sequence = 0
        try:
            stream = await self._client.responses.create(**self._create_kwargs(request, stream=True))
            async for event in stream:
                event_type = str(getattr(event, "type", ""))
                event_response = getattr(event, "response", None)
                if event_response is not None:
                    provider_response_id = getattr(event_response, "id", None) or provider_response_id

                if event_type == "response.created":
                    sequence += 1
                    yield AIStreamEvent(
                        type=AIStreamEventType.RESPONSE_CREATED,
                        sequence_number=sequence,
                        request_id=str(request.request_id),
                        provider_response_id=provider_response_id,
                    )
                elif event_type == "response.output_text.delta":
                    sequence += 1
                    yield AIStreamEvent(
                        type=AIStreamEventType.OUTPUT_TEXT_DELTA,
                        sequence_number=sequence,
                        request_id=str(request.request_id),
                        provider_response_id=provider_response_id,
                        delta=str(getattr(event, "delta", "")),
                    )
                elif event_type == "response.output_item.added":
                    item = getattr(event, "item", None)
                    tool_call = self._tool_call_from_item(item)
                    if tool_call:
                        sequence += 1
                        yield AIStreamEvent(
                            type=AIStreamEventType.TOOL_CALL_ADDED,
                            sequence_number=sequence,
                            request_id=str(request.request_id),
                            provider_response_id=provider_response_id,
                            tool_call=tool_call,
                        )
                elif event_type == "response.function_call_arguments.delta":
                    sequence += 1
                    yield AIStreamEvent(
                        type=AIStreamEventType.TOOL_CALL_ARGUMENTS_DELTA,
                        sequence_number=sequence,
                        request_id=str(request.request_id),
                        provider_response_id=provider_response_id,
                        delta=str(getattr(event, "delta", "")),
                        metadata={"item_id": getattr(event, "item_id", None), "output_index": getattr(event, "output_index", None)},
                    )
                elif event_type in {"response.completed", "response.incomplete"}:
                    if event_response is None:
                        raise AIProviderError(
                            "OpenAI terminal stream event did not contain a response",
                            code=AIErrorCode.UNKNOWN,
                            retryable=False,
                            provider="openai",
                        )
                    result = self._normalize_response(
                        request,
                        event_response,
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                    )
                    sequence += 1
                    yield AIStreamEvent(
                        type=(
                            AIStreamEventType.RESPONSE_COMPLETED
                            if result.response_status is AIResponseStatus.COMPLETED
                            else AIStreamEventType.RESPONSE_INCOMPLETE
                        ),
                        sequence_number=sequence,
                        request_id=str(request.request_id),
                        provider_response_id=result.provider_response_id,
                        final_result=result,
                    )
                    return
                elif event_type in {"response.failed", "error"}:
                    error = getattr(event_response, "error", None) if event_response is not None else getattr(event, "error", None)
                    message = getattr(error, "message", None) or "OpenAI streaming response failed"
                    raise AIProviderError(
                        message,
                        code=AIErrorCode.PROVIDER_UNAVAILABLE,
                        retryable=False,
                        provider="openai",
                        provider_request_id=self._request_id(event_response) if event_response else None,
                    )
        except asyncio.CancelledError:
            if provider_response_id:
                try:
                    await self.cancel(provider_response_id)
                except AIProviderError:
                    pass
            raise
        except AIProviderError:
            raise
        except Exception as exc:
            raise self._classify_exception(exc) from exc

        raise AIProviderError(
            "OpenAI stream ended without a terminal response event",
            code=AIErrorCode.CONNECTION,
            retryable=True,
            provider="openai",
        )

    async def cancel(self, response_id: str) -> bool:
        try:
            response = await self._client.responses.cancel(response_id)
        except Exception as exc:
            raise self._classify_exception(exc) from exc
        status = str(getattr(response, "status", ""))
        return status in {"cancelled", "canceled"}

    def _create_kwargs(self, request: AIRequest, *, stream: bool) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "input": (
                request.input
                if isinstance(request.input, str)
                else [item.model_dump(mode="json", exclude_none=True) for item in request.input]
            ),
            "max_output_tokens": request.max_output_tokens,
            "metadata": {**request.metadata, "verideploy_request_id": str(request.request_id)},
            "stream": stream,
            "store": request.store_provider_response,
            "background": request.background,
        }
        if request.instructions:
            kwargs["instructions"] = request.instructions
        if request.previous_response_id:
            kwargs["previous_response_id"] = request.previous_response_id
        if request.tools:
            kwargs["tools"] = [tool.model_dump(mode="json", exclude_none=True) for tool in request.tools]
        if request.tool_choice != "auto":
            kwargs["tool_choice"] = (
                request.tool_choice.model_dump(mode="json")
                if isinstance(request.tool_choice, AIFunctionToolChoice)
                else request.tool_choice
            )
        if request.structured_output is not None:
            kwargs["text"] = {
                "format": request.structured_output.model_dump(mode="json", by_alias=True, exclude_none=True)
            }
        return kwargs

    def _normalize_response(self, request: AIRequest, response: Any, *, elapsed_ms: float) -> AIResult:
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None) if usage is not None else None
        output_details = getattr(usage, "output_tokens_details", None) if usage is not None else None
        status = self._status(getattr(response, "status", None))
        return AIResult(
            request_id=request.request_id,
            provider=AIProviderName.OPENAI,
            model=request.model or "",
            output_text=str(getattr(response, "output_text", "") or ""),
            tool_calls=self._tool_calls(response),
            response_status=status,
            provider_response_id=getattr(response, "id", None),
            provider_request_id=self._request_id(response),
            usage=AIUsage(
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
                cached_input_tokens=getattr(input_details, "cached_tokens", None),
                reasoning_tokens=getattr(output_details, "reasoning_tokens", None),
            ),
            latency_ms=elapsed_ms,
            attempts=1,
            metadata={
                "openai_status": str(getattr(response, "status", "unknown")),
                "incomplete_reason": self._incomplete_reason(response),
            },
        )

    @classmethod
    def _tool_calls(cls, response: Any) -> list[AIToolCall]:
        calls: list[AIToolCall] = []
        for item in getattr(response, "output", None) or []:
            call = cls._tool_call_from_item(item)
            if call:
                calls.append(call)
        return calls

    @staticmethod
    def _tool_call_from_item(item: Any) -> AIToolCall | None:
        if item is None or str(getattr(item, "type", "")) != "function_call":
            return None
        call_id = getattr(item, "call_id", None) or getattr(item, "id", None)
        name = getattr(item, "name", None)
        if not call_id or not name:
            return None
        return AIToolCall(
            call_id=str(call_id),
            name=str(name),
            arguments_json=str(getattr(item, "arguments", "{}") or "{}"),
        )

    @staticmethod
    def _incomplete_reason(response: Any) -> str | None:
        details = getattr(response, "incomplete_details", None)
        return str(getattr(details, "reason", "")) or None if details is not None else None

    @staticmethod
    def _status(value: Any) -> AIResponseStatus:
        raw = str(value or "unknown").lower()
        try:
            return AIResponseStatus(raw)
        except ValueError:
            return AIResponseStatus.UNKNOWN

    @staticmethod
    def _request_id(response: Any) -> str | None:
        return getattr(response, "_request_id", None) or getattr(response, "request_id", None)

    @staticmethod
    def _classify_exception(exc: Exception) -> AIProviderError:
        name = type(exc).__name__
        status = getattr(exc, "status_code", None)
        provider_request_id = getattr(exc, "request_id", None)
        retry_after: float | None = None
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is not None:
            raw_retry_after = headers.get("retry-after")
            if raw_retry_after:
                try:
                    retry_after = float(raw_retry_after)
                except (TypeError, ValueError):
                    retry_after = None
        if name in {"AuthenticationError"} or status == 401:
            code, retryable = AIErrorCode.AUTHENTICATION, False
        elif name in {"PermissionDeniedError"} or status == 403:
            code, retryable = AIErrorCode.PERMISSION, False
        elif name in {"BadRequestError", "UnprocessableEntityError"} or status in {400, 422}:
            code, retryable = AIErrorCode.INVALID_REQUEST, False
        elif name == "RateLimitError" or status == 429:
            code, retryable = AIErrorCode.RATE_LIMITED, True
        elif name == "APITimeoutError" or status == 408:
            code, retryable = AIErrorCode.TIMEOUT, True
        elif name == "APIConnectionError":
            code, retryable = AIErrorCode.CONNECTION, True
        elif status == 409 or (isinstance(status, int) and status >= 500):
            code, retryable = AIErrorCode.PROVIDER_UNAVAILABLE, True
        else:
            code, retryable = AIErrorCode.UNKNOWN, False
        return AIProviderError(
            "AI provider request failed",
            code=code,
            retryable=retryable,
            provider="openai",
            status_code=status,
            retry_after_seconds=retry_after,
            provider_request_id=provider_request_id,
        )
