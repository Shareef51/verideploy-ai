from __future__ import annotations

import io
from typing import Any, Literal

from verideploy.multimodal.audio_transcription import ProviderTranscriptSegment, ProviderTranscriptionResult, TranscriptionProviderError


class OpenAITranscriptionProvider:
    """Official OpenAI SDK adapter. Retry ownership remains in AudioTranscriptionService."""

    def __init__(self, client: Any, *, response_mode: Literal["timestamped", "diarized"] = "timestamped") -> None:
        self._client = client
        self._response_mode = response_mode

    async def transcribe(self, *, audio_bytes: bytes, filename: str, mime_type: str, model: str, language: str | None) -> ProviderTranscriptionResult:
        file_obj = io.BytesIO(audio_bytes)
        file_obj.name = filename
        kwargs: dict[str, Any] = {"file": file_obj, "model": model}
        if self._response_mode == "diarized":
            # Current OpenAI diarization contract returns timestamped speaker segments in diarized_json.
            kwargs.update(response_format="diarized_json", chunking_strategy="auto")
        else:
            # Timestamp granularities require verbose_json. If the configured model does not support
            # this contract the provider returns a typed non-retryable error; no timestamps are fabricated.
            kwargs.update(response_format="verbose_json", timestamp_granularities=["segment"])
        if language:
            kwargs["language"] = language
        try:
            response = await self._client.audio.transcriptions.create(**kwargs)
        except Exception as exc:
            raise self._classify(exc) from exc

        raw_segments = self._get(response, "segments", []) or []
        segments: list[ProviderTranscriptSegment] = []
        for raw in raw_segments:
            start = self._get(raw, "start")
            end = self._get(raw, "end")
            text = str(self._get(raw, "text", "")).strip()
            if start is None or end is None or not text:
                continue
            speaker = self._get(raw, "speaker") or self._get(raw, "speaker_id")
            segments.append(
                ProviderTranscriptSegment(
                    start_seconds=float(start), end_seconds=float(end), text=text,
                    speaker=str(speaker) if speaker is not None else None,
                )
            )
        if not segments:
            raise TranscriptionProviderError("configured transcription response did not include timestamped segments", retryable=False)
        return ProviderTranscriptionResult(
            provider="openai", model=str(self._get(response, "model", model)), language=self._get(response, "language"),
            duration_seconds=self._float_or_none(self._get(response, "duration")),
            provider_request_id=self._get(response, "_request_id") or self._get(response, "request_id"), segments=segments,
        )

    @staticmethod
    def _get(value: Any, key: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _classify(exc: Exception) -> TranscriptionProviderError:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__
        retryable = name in {"APIConnectionError", "APITimeoutError", "RateLimitError"} or status in {408, 409, 429} or (isinstance(status, int) and status >= 500)
        retry_after = None
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers:
            try:
                retry_after = float(headers.get("retry-after")) if headers.get("retry-after") else None
            except (TypeError, ValueError):
                retry_after = None
        return TranscriptionProviderError("transcription provider request failed", retryable=retryable, retry_after_seconds=retry_after)
