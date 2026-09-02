from __future__ import annotations

from verideploy.observability.telemetry import extract_kafka_context, inject_kafka_headers, span

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from verideploy.multimodal.audio_transcription import AudioTranscriptionCommand, AudioTranscriptionRecord, AudioTranscriptionService

logger = logging.getLogger(__name__)
Emit = Callable[[str, dict[str, object]], Awaitable[None]]


class AudioTranscriptionJobCommand(BaseModel):
    """Kafka-safe command: object references only, never audio bytes."""
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    ingestion_job_id: UUID
    correlation_id: UUID
    original_filename: str = Field(min_length=1, max_length=255)
    declared_mime_type: str = Field(min_length=3, max_length=120)
    bucket: str = Field(min_length=3, max_length=63)
    object_key: str = Field(min_length=3, max_length=1024)
    object_version: str | None = Field(default=None, max_length=256)
    model: str = Field(min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=2, max_length=20)


class AudioObjectStore(Protocol):
    async def get_bytes(self, *, bucket: str, object_key: str, object_version: str | None) -> bytes: ...


class S3AudioObjectStore:
    def __init__(self, client) -> None:
        self.client = client

    async def get_bytes(self, *, bucket: str, object_key: str, object_version: str | None) -> bytes:
        def _read() -> bytes:
            kwargs = {"Bucket": bucket, "Key": object_key}
            if object_version:
                kwargs["VersionId"] = object_version
            response = self.client.get_object(**kwargs)
            body = response["Body"]
            try:
                return body.read()
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
        return await asyncio.to_thread(_read)


class AudioTranscriptionWorker:
    def __init__(self, service: AudioTranscriptionService, object_store: AudioObjectStore | None = None) -> None:
        self.service = service
        self.object_store = object_store

    async def handle(self, command: AudioTranscriptionCommand) -> AudioTranscriptionRecord:
        """Inner byte-level handler used after authorized object retrieval."""
        return await self.service.transcribe(command)

    async def handle_job(self, command: AudioTranscriptionJobCommand) -> AudioTranscriptionRecord:
        if self.object_store is None:
            raise RuntimeError("audio object store is required for job commands")
        audio_bytes = await self.object_store.get_bytes(
            bucket=command.bucket, object_key=command.object_key, object_version=command.object_version
        )
        return await self.service.transcribe(
            AudioTranscriptionCommand(
                tenant_id=command.tenant_id,
                ingestion_job_id=command.ingestion_job_id,
                correlation_id=command.correlation_id,
                original_filename=command.original_filename,
                declared_mime_type=command.declared_mime_type,
                audio_bytes=audio_bytes,
                model=command.model,
                language=command.language,
            )
        )


async def handle_audio_transcription_job(payload: bytes, worker: AudioTranscriptionWorker, emit: Emit) -> None:
    try:
        command = AudioTranscriptionJobCommand.model_validate_json(payload)
    except ValidationError as exc:
        logger.warning("invalid audio transcription command", extra={"error_count": exc.error_count()})
        await emit("audio.transcription.command.rejected", {"reason": "schema_validation_failed"})
        return
    try:
        result = await worker.handle_job(command)
    except Exception:
        await emit(
            "audio.transcription.failed",
            {"tenant_id": str(command.tenant_id), "ingestion_job_id": str(command.ingestion_job_id), "correlation_id": str(command.correlation_id)},
        )
        raise
    await emit("audio.transcription.completed", result.model_dump(mode="json"))


async def run_kafka_worker(worker: AudioTranscriptionWorker, brokers: str) -> None:
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    except ImportError as exc:
        raise RuntimeError("aiokafka is required to run the audio transcription worker") from exc
    consumer = AIOKafkaConsumer(
        "verideploy.commands.audio-transcription.v1",
        bootstrap_servers=brokers,
        group_id="verideploy-audio-transcription-v1",
        enable_auto_commit=False,
    )
    producer = AIOKafkaProducer(bootstrap_servers=brokers)
    await consumer.start(); await producer.start()
    try:
        async for message in consumer:
            async def emit(event_type: str, event_payload: dict[str, object]) -> None:
                envelope = {"event_type": event_type, "schema_version": "1.0", "payload": event_payload}
                await producer.send_and_wait(
                    "verideploy.events.audio-transcription.v1",
                    json.dumps(envelope, separators=(",", ":"), default=str).encode(),
                    key=str(event_payload.get("transcription_id") or event_payload.get("ingestion_job_id") or "unknown").encode(),
                    headers=inject_kafka_headers([("schema-version", b"1.0")]),
                )
            await handle_audio_transcription_job(message.value, worker, emit)
            await consumer.commit()
    finally:
        await consumer.stop(); await producer.stop()
