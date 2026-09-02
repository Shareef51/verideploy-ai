from __future__ import annotations

from verideploy.observability.telemetry import extract_kafka_context, inject_kafka_headers, span
import json, logging
from collections.abc import Awaitable, Callable
from typing import Any
from pydantic import ValidationError
from verideploy.multimodal.schemas import IngestionCommand
from verideploy.multimodal.service import IngestionService

logger=logging.getLogger(__name__)
Emit=Callable[[str, dict[str, Any]], Awaitable[None]]

async def handle_ingestion(payload: bytes, service: IngestionService, emit: Emit) -> None:
    try: command=IngestionCommand.model_validate_json(payload)
    except ValidationError as exc:
        logger.warning("invalid ingestion command", extra={"error_count":exc.error_count()}); await emit("ingestion.command.rejected", {"reason":"schema_validation_failed"}); return
    job,created=service.accept(command)
    if not created:
        for event in service.events(job.tenant_id, job.job_id): await emit(event.event_type, event.model_dump(mode="json"))
        return
    _,events=service.initialize(job.tenant_id, job.job_id)
    for event in events: await emit(event.event_type, event.model_dump(mode="json"))

async def run_kafka_worker(service: IngestionService, brokers: str) -> None:
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    except ImportError as exc: raise RuntimeError("aiokafka is required to run the ingestion worker") from exc
    consumer=AIOKafkaConsumer("verideploy.commands.ingestion.v1", bootstrap_servers=brokers, group_id="verideploy-ingestion-v1", enable_auto_commit=False)
    producer=AIOKafkaProducer(bootstrap_servers=brokers); await consumer.start(); await producer.start()
    try:
        async for message in consumer:
            async def emit(event_type: str, payload: dict[str, Any]) -> None:
                envelope=payload if {"event_id","sequence_number","job_id"}.issubset(payload) else {"event_type":event_type,"schema_version":"1.0","payload":payload}
                await producer.send_and_wait("verideploy.events.ingestion.v1", json.dumps(envelope,separators=(",",":"),default=str).encode(), key=str(payload.get("job_id","unknown")).encode(), headers=inject_kafka_headers([("schema-version",b"1.0")]))
            await handle_ingestion(message.value, service, emit); await consumer.commit()
    finally: await consumer.stop(); await producer.stop()
