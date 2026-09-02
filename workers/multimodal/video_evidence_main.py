from __future__ import annotations

import asyncio

from services.ai.video_evidence import get_video_evidence_service
from verideploy.config import get_settings
from verideploy.observability.telemetry import configure_telemetry
from workers.multimodal.video_evidence_worker import S3FrameArtifactStore, S3VideoObjectStore, VideoEvidenceWorker, run_kafka_worker


def _s3_client(settings):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required to run the video evidence worker") from exc
    return boto3.client("s3", endpoint_url=settings.s3_endpoint, region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value() if settings.s3_access_key else None,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None)


async def main() -> None:
    settings = get_settings()
    configure_telemetry(settings, service_name="verideploy-video-evidence-worker")
    client = _s3_client(settings)
    service = get_video_evidence_service()
    service.frame_store = S3FrameArtifactStore(client, settings.s3_bucket)
    worker = VideoEvidenceWorker(service, S3VideoObjectStore(client))
    await run_kafka_worker(worker, settings.kafka_brokers)


if __name__ == "__main__":
    asyncio.run(main())
