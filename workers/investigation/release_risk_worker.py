from __future__ import annotations

from verideploy.observability.telemetry import extract_kafka_context, inject_kafka_headers, span

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from verideploy.releases.schemas import ReleaseRiskCommand
from verideploy.releases.service import ReleaseRiskService
from verideploy.graphs.runtime import LangGraphRuntime

logger = logging.getLogger(__name__)


async def handle_release_risk_command(payload: bytes, service: ReleaseRiskService, emit: Callable[[str, dict[str, Any]], Awaitable[None]], *, runtime: LangGraphRuntime | None = None) -> None:
    try:
        command = ReleaseRiskCommand.model_validate_json(payload)
    except ValidationError as exc:
        logger.warning("invalid release risk command", extra={"error_count": exc.error_count()})
        await emit("release.risk.command.rejected", {"reason": "schema_validation_failed"})
        return

    record, created = service.accept(command)
    if not created and record.result is not None:
        await emit("release.risk.completed", record.model_dump(mode="json"))
        return
    await emit("release.risk.started", {"assessment_id": str(record.assessment_id), "tenant_id": str(record.tenant_id), "correlation_id": str(record.correlation_id)})
    if runtime is None:  # transport-independent compatibility for direct unit/API invocation
        completed = await asyncio.to_thread(service.assess, record.tenant_id, record.assessment_id)
    else:
        _, graph_result = await runtime.execute(
            tenant_id=record.tenant_id, correlation_id=str(record.correlation_id),
            graph_name="release_risk", graph_version="2.0.0", run_id=record.assessment_id,
            input_state={"input": {"assessment_id": str(record.assessment_id), "release_id": record.release_id,
                "policy": record.policy_input.model_dump(mode="json"),
                "human_review_threshold": service._human_review_threshold}},
        )
        completed = await asyncio.to_thread(service.complete_from_graph, record.tenant_id, record.assessment_id, graph_result["final_output"])
    await emit("release.risk.completed", completed.model_dump(mode="json"))


async def run_kafka_worker(service: ReleaseRiskService, runtime: LangGraphRuntime, brokers: str) -> None:
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    except ImportError as exc:
        raise RuntimeError("aiokafka is required to run the Kafka release-risk worker") from exc

    consumer = AIOKafkaConsumer("verideploy.commands.release-risk.v1", bootstrap_servers=brokers, group_id="verideploy-release-risk-v1", enable_auto_commit=False)
    producer = AIOKafkaProducer(bootstrap_servers=brokers)
    await consumer.start(); await producer.start()
    try:
        async for message in consumer:
            async def emit(event_type: str, event_payload: dict[str, Any]) -> None:
                envelope = {"event_type": event_type, "schema_version": "1.0", "payload": event_payload}
                await producer.send_and_wait("verideploy.events.release-risk.v1", json.dumps(envelope, separators=(",", ":")).encode(), headers=inject_kafka_headers([("schema-version", b"1.0")]))
            with span("kafka.consume release-risk", attributes={"messaging.system":"kafka","messaging.destination.name":message.topic}, context=extract_kafka_context(message.headers)):
                await handle_release_risk_command(message.value, service, emit, runtime=runtime)
                await consumer.commit()
    finally:
        await consumer.stop(); await producer.stop()
