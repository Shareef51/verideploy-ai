from __future__ import annotations

import asyncio

from services.ai.audio_transcription import get_audio_transcription_service
from verideploy.config import get_settings
from verideploy.observability.telemetry import configure_telemetry
from workers.multimodal.audio_transcription_worker import AudioTranscriptionWorker, S3AudioObjectStore, run_kafka_worker


def _s3_client(settings):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required to run the audio transcription worker") from exc
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value() if settings.s3_access_key else None,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None,
    )


async def main() -> None:
    settings = get_settings()
    configure_telemetry(settings, service_name="verideploy-audio-transcription-worker")
    if not settings.openai_transcription_model:
        raise RuntimeError("OPENAI_TRANSCRIPTION_MODEL must be configured for the audio transcription worker")
    worker = AudioTranscriptionWorker(
        get_audio_transcription_service(),
        S3AudioObjectStore(_s3_client(settings)),
    )
    await run_kafka_worker(worker, settings.kafka_brokers)


if __name__ == "__main__":
    asyncio.run(main())
