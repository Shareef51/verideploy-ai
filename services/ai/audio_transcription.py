from __future__ import annotations

import os
from functools import lru_cache

from verideploy.config import get_settings
from verideploy.multimodal.audio_openai import OpenAITranscriptionProvider
from verideploy.multimodal.audio_repository import SqlAlchemyTranscriptionRepository
from verideploy.multimodal.audio_transcription import (
    AudioTranscriptionService,
    DeterministicTranscriptionProvider,
    TranscriptRedactor,
)


def _runtime_database_url() -> tuple[str, bool]:
    configured = os.getenv("TRANSCRIPTION_DATABASE_URL")
    if configured:
        return configured, configured.startswith("sqlite")
    settings = get_settings()
    return settings.database_url, settings.app_env in {"development", "test"}


def _openai_client():
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - exercised in provisioned deployments
        raise RuntimeError("OpenAI SDK is required for OpenAI transcription provider") from exc
    settings = get_settings()
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI transcription provider")
    return AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), max_retries=0, timeout=settings.transcription_timeout_seconds)


@lru_cache
def get_audio_transcription_service() -> AudioTranscriptionService:
    settings = get_settings()
    url, create_schema = _runtime_database_url()
    repository = SqlAlchemyTranscriptionRepository(url, create_schema=create_schema)
    provider = (
        DeterministicTranscriptionProvider()
        if settings.app_env == "test" or settings.ai_provider == "test"
        else OpenAITranscriptionProvider(_openai_client(), response_mode=settings.transcription_response_mode)
    )
    return AudioTranscriptionService(
        provider=provider,
        repository=repository,
        redactor=TranscriptRedactor.from_json(settings.transcription_pii_patterns_json),
        max_audio_bytes=settings.max_audio_upload_bytes,
        max_attempts=settings.transcription_max_attempts,
    )
