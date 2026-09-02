from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.ai.audio_transcription import get_audio_transcription_service
from services.ai.main import app
from verideploy.multimodal.audio_openai import OpenAITranscriptionProvider
from verideploy.multimodal.audio_repository import SqlAlchemyTranscriptionRepository
from verideploy.multimodal.audio_transcription import (
    AudioTranscriptionCommand,
    AudioTranscriptionService,
    DeterministicTranscriptionProvider,
    ProviderTranscriptSegment,
    TranscriptRedactor,
    TranscriptionProviderError,
    TranscriptionStatus,
    validate_audio_bytes,
)
from workers.multimodal.audio_transcription_worker import AudioTranscriptionWorker


def _wav_bytes() -> bytes:
    return b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 24 + b"data" + b"\x00" * 8


def _command(*, tenant_id=None, job_id=None) -> AudioTranscriptionCommand:
    return AudioTranscriptionCommand(
        tenant_id=tenant_id or uuid4(),
        ingestion_job_id=job_id or uuid4(),
        correlation_id=uuid4(),
        original_filename="incident.wav",
        declared_mime_type="audio/wav",
        audio_bytes=_wav_bytes(),
        model="transcription-test-model",
        language="en",
    )


def _service(provider=None):
    return AudioTranscriptionService(
        provider=provider or DeterministicTranscriptionProvider(),
        repository=SqlAlchemyTranscriptionRepository("sqlite://", create_schema=True),
        redactor=TranscriptRedactor.from_json("[]"),
        max_audio_bytes=1024 * 1024,
        max_attempts=3,
    )


def test_content_signature_validation_rejects_fake_audio():
    assert validate_audio_bytes(_wav_bytes(), max_bytes=1024).mime_type.value == "audio/wav"
    with pytest.raises(ValueError, match="audio signature"):
        validate_audio_bytes(b"not actually audio", max_bytes=1024)


@pytest.mark.asyncio
async def test_transcription_persists_timestamped_redacted_evidence_and_speaker():
    provider = DeterministicTranscriptionProvider(
        [
            ProviderTranscriptSegment(start_seconds=0.0, end_seconds=1.5, text="Email me at analyst@example.com", speaker="speaker_0"),
            ProviderTranscriptSegment(start_seconds=1.5, end_seconds=2.5, text="authorization: Bearer tokenvalue123456", speaker="speaker_1"),
        ]
    )
    service = _service(provider)
    result = await service.transcribe(_command())
    assert result.status == TranscriptionStatus.COMPLETED
    assert [s.sequence_number for s in result.segments] == [1, 2]
    assert [s.speaker for s in result.segments] == ["speaker_0", "speaker_1"]
    assert "analyst@example.com" not in result.segments[0].text
    assert "tokenvalue123456" not in result.segments[1].text
    assert all(s.evidence_id.startswith("VD-AUDIO-") for s in result.segments)
    assert all(len(s.raw_text_sha256) == 64 for s in result.segments)


@pytest.mark.asyncio
async def test_retry_is_bounded_and_idempotent_replay_does_not_duplicate_segments():
    provider = DeterministicTranscriptionProvider(
        [ProviderTranscriptSegment(start_seconds=0, end_seconds=2, text="checkout service timeout")],
        failures_before_success=1,
    )
    service = _service(provider)
    command = _command()
    first = await service.transcribe(command)
    assert first.attempt_count == 2
    assert provider.calls == 2
    second = await service.transcribe(command)
    assert provider.calls == 2
    assert [s.segment_id for s in second.segments] == [s.segment_id for s in first.segments]
    assert len(second.segments) == 1


@pytest.mark.asyncio
async def test_terminal_failure_is_persisted_without_raw_provider_message():
    class BadProvider:
        async def transcribe(self, **kwargs):
            raise TranscriptionProviderError("sensitive upstream detail", retryable=False)

    service = _service(BadProvider())
    command = _command()
    with pytest.raises(TranscriptionProviderError):
        await service.transcribe(command)
    tid = service.transcription_id(command.tenant_id, command.ingestion_job_id, command.model)
    record = service.repository.get(command.tenant_id, tid)
    assert record is not None and record.status == TranscriptionStatus.FAILED
    assert record.error_message == "transcription provider request failed"
    assert "sensitive" not in record.error_message


@pytest.mark.asyncio
async def test_out_of_order_provider_segments_are_rejected_and_marked_failed():
    provider = DeterministicTranscriptionProvider([
        ProviderTranscriptSegment(start_seconds=2, end_seconds=3, text="later"),
        ProviderTranscriptSegment(start_seconds=1, end_seconds=1.5, text="earlier"),
    ])
    service = _service(provider)
    command = _command()
    with pytest.raises(ValueError, match="overlap or are out of order"):
        await service.transcribe(command)
    tid = service.transcription_id(command.tenant_id, command.ingestion_job_id, command.model)
    assert service.repository.get(command.tenant_id, tid).status == TranscriptionStatus.FAILED


@pytest.mark.asyncio
async def test_worker_uses_same_service_contract():
    service = _service()
    worker = AudioTranscriptionWorker(service)
    result = await worker.handle(_command())
    assert result.status == TranscriptionStatus.COMPLETED
    assert result.segments[0].text == "deterministic transcript"


@pytest.mark.asyncio
async def test_openai_adapter_requests_timestamped_verbose_transcription_and_preserves_speaker():
    captured = {}

    class Transcriptions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                model="configured-model",
                language="en",
                duration=3.0,
                _request_id="req_audio_1",
                segments=[SimpleNamespace(start=0.0, end=3.0, text="incident commander speaking", speaker="speaker_A")],
            )

    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=Transcriptions()))
    result = await OpenAITranscriptionProvider(client).transcribe(
        audio_bytes=_wav_bytes(), filename="incident.wav", mime_type="audio/wav", model="configured-model", language="en"
    )
    assert captured["response_format"] == "verbose_json"
    assert captured["timestamp_granularities"] == ["segment"]
    assert captured["model"] == "configured-model"
    assert result.provider_request_id == "req_audio_1"
    assert result.segments[0].speaker == "speaker_A"


@pytest.mark.asyncio
async def test_openai_diarized_mode_uses_diarized_json_without_timestamp_granularities():
    captured = {}
    class Transcriptions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(duration=2.0, segments=[SimpleNamespace(start=0, end=2, text="hello", speaker="A")])
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=Transcriptions()))
    result = await OpenAITranscriptionProvider(client, response_mode="diarized").transcribe(
        audio_bytes=_wav_bytes(), filename="meeting.wav", mime_type="audio/wav", model="configured-diarization-model", language="en"
    )
    assert captured["response_format"] == "diarized_json"
    assert captured["chunking_strategy"] == "auto"
    assert "timestamp_granularities" not in captured
    assert result.segments[0].speaker == "A"


@pytest.mark.asyncio
async def test_openai_adapter_refuses_to_fabricate_timestamps():
    class Transcriptions:
        async def create(self, **kwargs):
            return SimpleNamespace(text="untimed text", segments=[])
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=Transcriptions()))
    with pytest.raises(TranscriptionProviderError, match="timestamped segments"):
        await OpenAITranscriptionProvider(client).transcribe(
            audio_bytes=_wav_bytes(), filename="incident.wav", mime_type="audio/wav", model="configured-model", language=None
        )


def test_configured_pii_regex_is_applied():
    redactor = TranscriptRedactor.from_json(r'["INC-[0-9]{6}"]')
    value = redactor.redact("ticket INC-123456 assigned")
    assert value == "ticket [REDACTED] assigned"


def test_private_transcription_api_requires_trusted_identity_and_tenant_scope():
    tenant_id = uuid4()
    service = _service()
    command = _command(tenant_id=tenant_id)
    import asyncio
    record = asyncio.run(service.transcribe(command))
    app.dependency_overrides[get_audio_transcription_service] = lambda: service
    try:
        client = TestClient(app)
        url = f"/internal/v1/audio/transcriptions/{record.transcription_id}"
        response = client.get(url, headers={"x-tenant-id": str(tenant_id)})
        assert response.status_code == 401
        response = client.get(url, headers={"x-internal-service": "verideploy-investigation-worker", "x-tenant-id": str(uuid4())})
        assert response.status_code == 404
        response = client.get(url, headers={"x-internal-service": "verideploy-investigation-worker", "x-tenant-id": str(tenant_id)})
        assert response.status_code == 200
        assert response.json()["segments"][0]["evidence_id"].startswith("VD-AUDIO-")
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_kafka_job_command_uses_object_reference_not_audio_bytes():
    from workers.multimodal.audio_transcription_worker import AudioTranscriptionJobCommand, AudioTranscriptionWorker

    class Store:
        async def get_bytes(self, *, bucket, object_key, object_version):
            assert bucket == "verideploy-evidence"
            assert object_key == "tenant/audio/incident.wav"
            return _wav_bytes()

    service = _service()
    worker = AudioTranscriptionWorker(service, Store())
    command = AudioTranscriptionJobCommand(
        tenant_id=uuid4(), ingestion_job_id=uuid4(), correlation_id=uuid4(), original_filename="incident.wav",
        declared_mime_type="audio/wav", bucket="verideploy-evidence", object_key="tenant/audio/incident.wav",
        object_version=None, model="transcription-test-model", language="en"
    )
    payload = command.model_dump(mode="json")
    assert "audio_bytes" not in payload
    result = await worker.handle_job(command)
    assert result.status == TranscriptionStatus.COMPLETED
