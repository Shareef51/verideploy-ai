from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid5, NAMESPACE_URL

from pydantic import BaseModel, ConfigDict, Field, model_validator

from verideploy.llm.redaction import redact_text


class TranscriptionStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AudioFormat(StrEnum):
    WAV = "audio/wav"
    MP3 = "audio/mpeg"
    M4A = "audio/mp4"


class ProviderTranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1)
    speaker: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_time(self) -> "ProviderTranscriptSegment":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("segment end must be greater than start")
        return self


class ProviderTranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    language: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    provider_request_id: str | None = None
    segments: list[ProviderTranscriptSegment]


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: UUID
    transcription_id: UUID
    tenant_id: UUID
    sequence_number: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    speaker: str | None = None
    text: str
    raw_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_id: str = Field(pattern=r"^VD-AUDIO-[A-F0-9]{12}$")


class AudioTranscriptionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcription_id: UUID
    tenant_id: UUID
    ingestion_job_id: UUID
    correlation_id: UUID
    model: str
    audio_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    detected_mime_type: AudioFormat
    status: TranscriptionStatus
    language: str | None = None
    duration_seconds: float | None = None
    provider_request_id: str | None = None
    attempt_count: int = 0
    error_code: str | None = None
    error_message: str | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AudioTranscriptionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    ingestion_job_id: UUID
    correlation_id: UUID
    original_filename: str = Field(min_length=1, max_length=255)
    declared_mime_type: str = Field(min_length=3, max_length=120)
    audio_bytes: bytes = Field(min_length=1)
    model: str = Field(min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=2, max_length=20)


class TranscriptionProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class TranscriptionProvider(Protocol):
    async def transcribe(
        self, *, audio_bytes: bytes, filename: str, mime_type: str, model: str, language: str | None
    ) -> ProviderTranscriptionResult: ...


class TranscriptionRepository(Protocol):
    def get(self, tenant_id: UUID, transcription_id: UUID) -> AudioTranscriptionRecord | None: ...
    def create_or_get(self, record: AudioTranscriptionRecord) -> tuple[AudioTranscriptionRecord, bool]: ...
    def mark_processing(self, tenant_id: UUID, transcription_id: UUID, attempt_count: int) -> None: ...
    def complete(self, record: AudioTranscriptionRecord) -> AudioTranscriptionRecord: ...
    def fail(self, tenant_id: UUID, transcription_id: UUID, *, attempt_count: int, error_code: str, error_message: str) -> None: ...


@dataclass(frozen=True)
class AudioValidationResult:
    mime_type: AudioFormat
    sha256: str


def validate_audio_bytes(audio_bytes: bytes, *, max_bytes: int) -> AudioValidationResult:
    if not audio_bytes:
        raise ValueError("audio payload is empty")
    if len(audio_bytes) > max_bytes:
        raise ValueError("audio exceeds configured size limit")
    detected: AudioFormat | None = None
    if len(audio_bytes) >= 12 and audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        detected = AudioFormat.WAV
    elif audio_bytes.startswith(b"ID3") or (len(audio_bytes) >= 2 and audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xE0) == 0xE0):
        detected = AudioFormat.MP3
    elif len(audio_bytes) >= 12 and audio_bytes[4:8] == b"ftyp":
        detected = AudioFormat.M4A
    if detected is None:
        raise ValueError("unsupported or invalid audio signature")
    return AudioValidationResult(mime_type=detected, sha256=hashlib.sha256(audio_bytes).hexdigest())


class TranscriptRedactor:
    _DEFAULT_PATTERNS = (
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)"),
    )

    def __init__(self, extra_patterns: list[str] | None = None) -> None:
        self._patterns = list(self._DEFAULT_PATTERNS)
        for pattern in extra_patterns or []:
            self._patterns.append(re.compile(pattern, re.IGNORECASE))

    @classmethod
    def from_json(cls, raw: str) -> "TranscriptRedactor":
        try:
            value = json.loads(raw or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("TRANSCRIPTION_PII_PATTERNS_JSON must be valid JSON") from exc
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError("TRANSCRIPTION_PII_PATTERNS_JSON must be a JSON array of regex strings")
        return cls(value)

    def redact(self, text: str) -> str:
        value = redact_text(text)
        for pattern in self._patterns:
            value = pattern.sub("[REDACTED]", value)
        return value


class AudioTranscriptionService:
    def __init__(
        self,
        *,
        provider: TranscriptionProvider,
        repository: TranscriptionRepository,
        redactor: TranscriptRedactor,
        max_audio_bytes: int,
        max_attempts: int = 3,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.redactor = redactor
        self.max_audio_bytes = max_audio_bytes
        self.max_attempts = max_attempts

    @staticmethod
    def transcription_id(tenant_id: UUID, ingestion_job_id: UUID, model: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"verideploy:audio:{tenant_id}:{ingestion_job_id}:{model}")

    async def transcribe(self, command: AudioTranscriptionCommand) -> AudioTranscriptionRecord:
        validation = validate_audio_bytes(command.audio_bytes, max_bytes=self.max_audio_bytes)
        transcription_id = self.transcription_id(command.tenant_id, command.ingestion_job_id, command.model)
        now = datetime.now(UTC)
        existing = self.repository.get(command.tenant_id, transcription_id)
        if existing and existing.status == TranscriptionStatus.COMPLETED:
            if existing.audio_sha256 != validation.sha256:
                raise ValueError("idempotent transcription identity refers to different audio content")
            return existing

        seed = AudioTranscriptionRecord(
            transcription_id=transcription_id,
            tenant_id=command.tenant_id,
            ingestion_job_id=command.ingestion_job_id,
            correlation_id=command.correlation_id,
            model=command.model,
            audio_sha256=validation.sha256,
            detected_mime_type=validation.mime_type,
            status=TranscriptionStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        current, _ = self.repository.create_or_get(seed)
        if current.audio_sha256 != validation.sha256:
            raise ValueError("idempotent transcription identity refers to different audio content")

        last_error: TranscriptionProviderError | None = None
        for attempt in range(max(1, current.attempt_count + 1), self.max_attempts + 1):
            self.repository.mark_processing(command.tenant_id, transcription_id, attempt)
            try:
                provider_result = await self.provider.transcribe(
                    audio_bytes=command.audio_bytes,
                    filename=command.original_filename,
                    mime_type=validation.mime_type.value,
                    model=command.model,
                    language=command.language,
                )
                record = self._build_completed(seed, provider_result, attempt)
                return self.repository.complete(record)
            except TranscriptionProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.max_attempts:
                    self.repository.fail(
                        command.tenant_id,
                        transcription_id,
                        attempt_count=attempt,
                        error_code="provider_error",
                        error_message="transcription provider request failed",
                    )
                    raise
                await asyncio.sleep(exc.retry_after_seconds or min(0.1 * 2 ** (attempt - 1), 1.0))
            except Exception:
                self.repository.fail(
                    command.tenant_id,
                    transcription_id,
                    attempt_count=attempt,
                    error_code="processing_error",
                    error_message="transcription processing failed",
                )
                raise
        assert last_error is not None
        raise last_error

    def _build_completed(
        self, seed: AudioTranscriptionRecord, provider_result: ProviderTranscriptionResult, attempt: int
    ) -> AudioTranscriptionRecord:
        segments: list[TranscriptSegment] = []
        previous_end = -1.0
        for index, segment in enumerate(provider_result.segments, start=1):
            if segment.start_seconds < previous_end:
                raise ValueError("provider transcript segments overlap or are out of order")
            previous_end = segment.end_seconds
            segment_id = uuid5(NAMESPACE_URL, f"{seed.transcription_id}:segment:{index}:{segment.start_seconds:.3f}:{segment.end_seconds:.3f}")
            evidence_id = "VD-AUDIO-" + hashlib.sha256(str(segment_id).encode()).hexdigest()[:12].upper()
            segments.append(
                TranscriptSegment(
                    segment_id=segment_id,
                    transcription_id=seed.transcription_id,
                    tenant_id=seed.tenant_id,
                    sequence_number=index,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    speaker=segment.speaker,
                    text=self.redactor.redact(segment.text),
                    raw_text_sha256=hashlib.sha256(segment.text.encode("utf-8")).hexdigest(),
                    evidence_id=evidence_id,
                )
            )
        if not segments:
            raise ValueError("provider returned no transcript segments")
        return seed.model_copy(
            update={
                "status": TranscriptionStatus.COMPLETED,
                "language": provider_result.language,
                "duration_seconds": provider_result.duration_seconds,
                "provider_request_id": provider_result.provider_request_id,
                "attempt_count": attempt,
                "segments": segments,
                "updated_at": datetime.now(UTC),
                "error_code": None,
                "error_message": None,
            }
        )


class DeterministicTranscriptionProvider:
    """Paid-API-free provider for deterministic tests and recruiter demo fixtures."""
    def __init__(self, segments: list[ProviderTranscriptSegment] | None = None, *, failures_before_success: int = 0) -> None:
        self.segments = segments or [ProviderTranscriptSegment(start_seconds=0, end_seconds=1, text="deterministic transcript")]
        self.failures_before_success = failures_before_success
        self.calls = 0

    async def transcribe(self, *, audio_bytes: bytes, filename: str, mime_type: str, model: str, language: str | None) -> ProviderTranscriptionResult:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise TranscriptionProviderError("temporary transcription failure", retryable=True)
        return ProviderTranscriptionResult(
            provider="deterministic",
            model=model,
            language=language or "en",
            duration_seconds=max(segment.end_seconds for segment in self.segments),
            provider_request_id=f"test-transcription-{self.calls}",
            segments=self.segments,
        )
