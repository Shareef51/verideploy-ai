from __future__ import annotations

from verideploy.observability.telemetry import extract_kafka_context, inject_kafka_headers, span

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from verideploy.postmortems.schemas import CreatePostmortemCommand
from verideploy.postmortems.service import PostmortemEligibilityError, PostmortemService

logger = logging.getLogger(__name__)
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


async def handle_postmortem_command(payload: bytes, service: PostmortemService, emit: Emit) -> None:
    try:
        command = CreatePostmortemCommand.model_validate_json(payload)
    except ValidationError as exc:
        logger.warning("invalid postmortem command", extra={"error_count": exc.error_count()})
        await emit("postmortem.command.rejected", {"reason": "schema_validation_failed"})
        return
    try:
        record, created = service.create(command)
    except KeyError:
        await emit("postmortem.command.rejected", {"reason": "investigation_not_found", "postmortem_id": str(command.postmortem_id)})
        return
    except PostmortemEligibilityError as exc:
        await emit("postmortem.command.rejected", {"reason": "source_not_eligible", "message": str(exc), "postmortem_id": str(command.postmortem_id)})
        return
    await emit("postmortem.generated" if created else "postmortem.replayed", record.model_dump(mode="json"))


async def run_kafka_worker(service: PostmortemService, brokers: str) -> None:
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    except ImportError as exc:
        raise RuntimeError("aiokafka is required to run the postmortem worker") from exc
    consumer = AIOKafkaConsumer("verideploy.commands.postmortem.v1", bootstrap_servers=brokers, group_id="verideploy-postmortem-v1", enable_auto_commit=False)
    producer = AIOKafkaProducer(bootstrap_servers=brokers)
    await consumer.start(); await producer.start()
    try:
        async for message in consumer:
            async def emit(event_type: str, event_payload: dict[str, Any]) -> None:
                envelope = {"event_type": event_type, "schema_version": "1.0", "payload": event_payload}
                await producer.send_and_wait("verideploy.events.postmortem.v1", json.dumps(envelope, separators=(",", ":"), default=str).encode(), headers=inject_kafka_headers([("schema-version", b"1.0")]))
            with span("kafka.consume postmortem", attributes={"messaging.system":"kafka","messaging.destination.name":message.topic}, context=extract_kafka_context(message.headers)):
                await handle_postmortem_command(message.value, service, emit)
                await consumer.commit()
    finally:
        await consumer.stop(); await producer.stop()
