from __future__ import annotations

from verideploy.observability.telemetry import extract_kafka_context, inject_kafka_headers, span

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from verideploy.multimodal.video_evidence import LocalFrameArtifactStore, VideoEvidenceCommand, VideoEvidenceRecord, VideoEvidenceService

logger = logging.getLogger(__name__)
Emit = Callable[[str, dict[str, object]], Awaitable[None]]


class VideoEvidenceJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    ingestion_job_id: UUID
    correlation_id: UUID
    original_filename: str = Field(min_length=1, max_length=255)
    declared_mime_type: str = Field(min_length=3, max_length=120)
    bucket: str = Field(min_length=3, max_length=63)
    object_key: str = Field(min_length=3, max_length=1024)
    object_version: str | None = Field(default=None, max_length=256)
    transcription_model: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, min_length=2, max_length=20)


class VideoObjectStore(Protocol):
    async def get_bytes(self, *, bucket: str, object_key: str, object_version: str | None) -> bytes: ...


class S3VideoObjectStore:
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
                if callable(close): close()
        return await asyncio.to_thread(_read)


class S3FrameArtifactStore(LocalFrameArtifactStore):
    def __init__(self, client, bucket: str) -> None:
        super().__init__("data/processed/video_frames")
        self.client = client
        self.bucket = bucket

    async def put_frame(self, *, tenant_id: UUID, video_job_id: UUID, frame_id: UUID, image_bytes: bytes) -> str:
        key = f"processed/video-frames/{tenant_id}/{video_job_id}/{frame_id}.jpg"
        await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=image_bytes, ContentType="image/jpeg")
        return f"s3://{self.bucket}/{key}"


class VideoEvidenceWorker:
    def __init__(self, service: VideoEvidenceService, object_store: VideoObjectStore) -> None:
        self.service = service
        self.object_store = object_store

    async def handle_job(self, command: VideoEvidenceJobCommand, emit: Emit | None = None) -> VideoEvidenceRecord:
        video_bytes = await self.object_store.get_bytes(bucket=command.bucket, object_key=command.object_key, object_version=command.object_version)
        return await self.service.process(VideoEvidenceCommand(
            tenant_id=command.tenant_id, ingestion_job_id=command.ingestion_job_id, correlation_id=command.correlation_id,
            original_filename=command.original_filename, declared_mime_type=command.declared_mime_type, video_bytes=video_bytes,
            transcription_model=command.transcription_model, language=command.language,
        ), progress=emit)


async def handle_video_evidence_job(payload: bytes, worker: VideoEvidenceWorker, emit: Emit) -> None:
    try:
        command = VideoEvidenceJobCommand.model_validate_json(payload)
    except ValidationError as exc:
        logger.warning("invalid video evidence command", extra={"error_count": exc.error_count()})
        await emit("video.evidence.command.rejected", {"reason": "schema_validation_failed"})
        return
    try:
        result = await worker.handle_job(command, emit)
    except Exception:
        await emit("video.processing.failed", {"tenant_id": str(command.tenant_id), "ingestion_job_id": str(command.ingestion_job_id), "correlation_id": str(command.correlation_id)})
        raise
    await emit("video.evidence.completed", result.model_dump(mode="json"))


async def run_kafka_worker(worker: VideoEvidenceWorker, brokers: str) -> None:
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    except ImportError as exc:
        raise RuntimeError("aiokafka is required to run the video evidence worker") from exc
    consumer = AIOKafkaConsumer("verideploy.commands.video-evidence.v1", bootstrap_servers=brokers, group_id="verideploy-video-evidence-v1", enable_auto_commit=False)
    producer = AIOKafkaProducer(bootstrap_servers=brokers)
    await consumer.start(); await producer.start()
    try:
        async for message in consumer:
            async def emit(event_type: str, event_payload: dict[str, object]) -> None:
                envelope = {"event_type": event_type, "schema_version": "1.0", "payload": event_payload}
                await producer.send_and_wait("verideploy.events.video-evidence.v1", json.dumps(envelope, separators=(",", ":"), default=str).encode(),
                    key=str(event_payload.get("video_job_id") or event_payload.get("ingestion_job_id") or "unknown").encode(), headers=inject_kafka_headers([("schema-version", b"1.0")]))
            await handle_video_evidence_job(message.value, worker, emit)
            await consumer.commit()
    finally:
        await consumer.stop(); await producer.stop()
