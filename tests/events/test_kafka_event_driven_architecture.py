from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

import pytest

from verideploy.events import EventEnvelope, OrderedInbox, ReplayWindow, RetryPolicy, TopicRegistry


ROOT = Path(__file__).resolve().parents[2]


def registry() -> TopicRegistry:
    return TopicRegistry.from_mapping(json.loads((ROOT / "config/kafka/topics.json").read_text()))


def event(seq: int, *, tenant: str = "tenant-a", aggregate: str = "inv-1", event_id: UUID | None = None) -> EventEnvelope:
    kwargs = {} if event_id is None else {"event_id": event_id}
    return EventEnvelope(
        event_type="investigation.progressed",
        tenant_id=tenant,
        aggregate_id=aggregate,
        ordering_key=f"{tenant}:{aggregate}",
        sequence_number=seq,
        payload={"status": f"step-{seq}"},
        correlation_id="corr-1",
        producer="test-worker",
        schema_family="investigation-event",
        **kwargs,
    )


def test_topic_registry_partitions_by_stable_ordering_key_and_rejects_schema_drift() -> None:
    topics = registry()
    topic = "verideploy.events.investigation.v1"
    assert topics.partition(topic, "tenant-a:inv-1") == topics.partition(topic, "tenant-a:inv-1")
    assert 0 <= topics.partition(topic, "tenant-a:inv-1") < topics.get(topic).partitions
    topics.assert_family_compatible(topic, "investigation-event", "1.4")
    with pytest.raises(ValueError, match="schema family"):
        topics.assert_family_compatible(topic, "release-risk-event", "1.0")
    with pytest.raises(ValueError, match="major version"):
        topics.assert_family_compatible(topic, "investigation-event", "2.0")


def test_duplicate_and_out_of_order_events_converge_to_authoritative_sequence() -> None:
    inbox = OrderedInbox()
    applied: list[int] = []
    assert inbox.accept(event(3), lambda item: applied.append(item.sequence_number)).status == "buffered"
    first = event(1)
    assert inbox.accept(first, lambda item: applied.append(item.sequence_number)).applied_sequences == (1,)
    duplicate = inbox.accept(first, lambda item: applied.append(item.sequence_number))
    assert duplicate.status == "duplicate"
    result = inbox.accept(event(2), lambda item: applied.append(item.sequence_number))
    assert result.applied_sequences == (2, 3)
    assert result.high_watermark == 3
    assert applied == [1, 2, 3]


def test_tenant_and_aggregate_ordering_are_isolated() -> None:
    inbox = OrderedInbox()
    state: dict[tuple[str, str], list[int]] = {}

    def apply(item: EventEnvelope) -> None:
        state.setdefault((item.tenant_id, item.aggregate_id), []).append(item.sequence_number)

    inbox.accept(event(2, tenant="tenant-a", aggregate="x"), apply)
    inbox.accept(event(1, tenant="tenant-b", aggregate="x"), apply)
    inbox.accept(event(1, tenant="tenant-a", aggregate="x"), apply)
    assert state[("tenant-a", "x")] == [1, 2]
    assert state[("tenant-b", "x")] == [1]
    assert inbox.high_watermark("tenant-a", "x") == 2
    assert inbox.high_watermark("tenant-b", "x") == 1


def test_retry_policy_routes_terminal_failure_to_dlq_and_replay_is_bounded() -> None:
    policy = RetryPolicy(max_attempts=4, backoff_seconds=(1, 5, 30))
    retry = policy.decide("base", 2, "verideploy.retry.platform.v1", "verideploy.dlq.platform.v1")
    assert retry.destination_topic == "verideploy.retry.platform.v1" and retry.delay_seconds == 5 and not retry.terminal
    dlq = policy.decide("base", 4, "verideploy.retry.platform.v1", "verideploy.dlq.platform.v1")
    assert dlq.destination_topic == "verideploy.dlq.platform.v1" and dlq.terminal
    replay = ReplayWindow.bounded(topic="verideploy.events.investigation.v1", tenant_id="tenant-a", requested_by="security-admin", reason="recover missed event", ttl_minutes=30)
    assert replay.from_sequence == 1
    with pytest.raises(ValueError, match="120"):
        ReplayWindow.bounded(topic="x", tenant_id="t", requested_by="u", reason="r", ttl_minutes=121)


@pytest.mark.asyncio
async def test_many_concurrent_duplicate_deliveries_apply_once() -> None:
    inbox = OrderedInbox()
    item = event(1)
    applied = 0
    lock = asyncio.Lock()

    async def deliver() -> str:
        nonlocal applied
        await asyncio.sleep(0)
        async with lock:
            def apply(_: EventEnvelope) -> None:
                nonlocal applied
                applied += 1
            return inbox.accept(item, apply).status

    statuses = await asyncio.gather(*(deliver() for _ in range(40)))
    assert applied == 1
    assert statuses.count("applied") == 1
    assert statuses.count("duplicate") == 39
