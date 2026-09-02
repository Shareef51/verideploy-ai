from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from verideploy.investigations.schemas import CancelInvestigationCommand, CreateInvestigationCommand
from verideploy.investigations.service import InvestigationService
from verideploy.graphs.runtime import LangGraphRuntime
from verideploy.graphs.runtime import GraphRunStatus
from verideploy.observability.telemetry import extract_kafka_context, inject_kafka_headers, span

logger = logging.getLogger(__name__)
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


async def handle_create(payload: bytes, service: InvestigationService, emit: Emit, *, runtime: LangGraphRuntime | None = None, complete_workflow: bool = False) -> None:
    try:
        command = CreateInvestigationCommand.model_validate_json(payload)
    except ValidationError as exc:
        logger.warning("invalid investigation command", extra={"error_count": exc.error_count()})
        await emit("investigation.command.rejected", {"reason": "schema_validation_failed"})
        return

    record, created = service.accept(command)
    if not created:
        for event in service.events(record.tenant_id, record.investigation_id):
            await emit(event.event_type, event.model_dump(mode="json"))
        return

    _, events = service.initialize(record.tenant_id, record.investigation_id)
    for event in events:
        await emit(event.event_type, event.model_dump(mode="json"))
    if complete_workflow:
        if runtime is None:
            raise RuntimeError("incident workflow completion requires LangGraphRuntime")
        graph_record, graph_result = await runtime.execute(
            tenant_id=record.tenant_id, correlation_id=str(record.correlation_id),
            graph_name="incident_rca", graph_version="2.0.0", run_id=record.investigation_id,
            input_state={"investigation_id": str(record.investigation_id), "user_id": str(record.requested_by),
                "input": {"query": record.query, "incident_id": record.incident_id}},
        )
        if graph_record.status == GraphRunStatus.WAITING_FOR_APPROVAL:
            await emit("investigation.approval.required", {"investigation_id":str(record.investigation_id),"run_id":str(graph_record.run_id),"interrupts":[getattr(x,"value",x) for x in graph_result.get("__interrupt__",[])]})
            return
        _, rca_events = service.complete_rca(record.tenant_id, record.investigation_id, graph_result)
        for event in rca_events:
            await emit(event.event_type, event.model_dump(mode="json"))


async def handle_cancel(payload: bytes, service: InvestigationService, emit: Emit) -> None:
    try:
        command = CancelInvestigationCommand.model_validate_json(payload)
    except ValidationError as exc:
        logger.warning("invalid cancellation command", extra={"error_count": exc.error_count()})
        await emit("investigation.cancel.command.rejected", {"reason": "schema_validation_failed"})
        return
    try:
        _, events = service.cancel(command.tenant_id, command.investigation_id, command.reason)
    except KeyError:
        await emit("investigation.cancel.command.rejected", {"reason": "investigation_not_found", "investigation_id": str(command.investigation_id)})
        return
    for event in events:
        await emit(event.event_type, event.model_dump(mode="json"))


async def run_kafka_worker(service: InvestigationService, runtime: LangGraphRuntime, brokers: str) -> None:
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    except ImportError as exc:
        raise RuntimeError("aiokafka is required to run the investigation worker") from exc

    topics = ["verideploy.commands.investigation.v1", "verideploy.commands.investigation-cancel.v1"]
    consumer = AIOKafkaConsumer(*topics, bootstrap_servers=brokers, group_id="verideploy-investigation-v1", enable_auto_commit=False)
    producer = AIOKafkaProducer(bootstrap_servers=brokers)
    await consumer.start(); await producer.start()
    try:
        async for message in consumer:
            async def emit(event_type: str, event_payload: dict[str, Any]) -> None:
                envelope = event_payload if {"event_id", "sequence_number", "investigation_id"}.issubset(event_payload) else {
                    "event_type": event_type, "schema_version": "1.0", "payload": event_payload,
                }
                await producer.send_and_wait(
                    "verideploy.events.investigation.v1",
                    json.dumps(envelope, separators=(",", ":"), default=str).encode(),
                    key=str(event_payload.get("investigation_id", "unknown")).encode(),
                    headers=inject_kafka_headers([("schema-version", b"1.0")]),
                )
            parent_context = extract_kafka_context(message.headers)
            with span("kafka.consume investigation", attributes={"messaging.system": "kafka", "messaging.destination.name": message.topic, "messaging.operation": "process"}, context=parent_context):
                if message.topic.endswith("investigation-cancel.v1"):
                    await handle_cancel(message.value, service, emit)
                else:
                    await handle_create(message.value, service, emit, runtime=runtime, complete_workflow=True)
                await consumer.commit()
    finally:
        await consumer.stop(); await producer.stop()
