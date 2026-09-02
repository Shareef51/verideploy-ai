from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Callable, Iterable, Mapping
from uuid import UUID, uuid4


class TopicKind(StrEnum):
    COMMAND = "command"
    EVENT = "event"
    RETRY = "retry"
    DLQ = "dlq"


@dataclass(frozen=True)
class TopicSpec:
    name: str
    kind: TopicKind
    partitions: int
    replication_factor: int
    retention_ms: int
    schema_family: str
    compatibility: str = "BACKWARD"

    def __post_init__(self) -> None:
        if self.partitions < 1:
            raise ValueError("partitions must be positive")
        if self.replication_factor < 1:
            raise ValueError("replication_factor must be positive")
        if self.compatibility not in {"BACKWARD", "FULL"}:
            raise ValueError("unsupported schema compatibility mode")


class TopicRegistry:
    def __init__(self, specs: Iterable[TopicSpec]) -> None:
        items = list(specs)
        self._specs = {spec.name: spec for spec in items}
        if len(self._specs) != len(items):
            raise ValueError("duplicate Kafka topic specification")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TopicRegistry":
        defaults = raw.get("defaults", {})
        specs: list[TopicSpec] = []
        for item in raw.get("topics", []):
            specs.append(
                TopicSpec(
                    name=str(item["name"]),
                    kind=TopicKind(str(item["kind"])),
                    partitions=int(item.get("partitions", defaults.get("partitions", 12))),
                    replication_factor=int(item.get("replication_factor", defaults.get("replication_factor", 3))),
                    retention_ms=int(item.get("retention_ms", defaults.get("retention_ms", 604_800_000))),
                    schema_family=str(item["schema_family"]),
                    compatibility=str(item.get("compatibility", defaults.get("compatibility", "BACKWARD"))),
                )
            )
        return cls(specs)

    def get(self, topic: str) -> TopicSpec:
        try:
            return self._specs[topic]
        except KeyError as exc:
            raise KeyError(f"unregistered Kafka topic: {topic}") from exc

    def partition(self, topic: str, ordering_key: str) -> int:
        spec = self.get(topic)
        if not ordering_key.strip():
            raise ValueError("ordering_key is required")
        digest = hashlib.sha256(ordering_key.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % spec.partitions

    def assert_family_compatible(self, topic: str, schema_family: str, schema_version: str) -> None:
        spec = self.get(topic)
        if schema_family != spec.schema_family:
            raise ValueError("schema family does not match topic contract")
        major = schema_version.split(".", 1)[0]
        if not major.isdigit() or int(major) != 1:
            raise ValueError("unsupported event schema major version")


@dataclass(frozen=True)
class EventEnvelope:
    event_type: str
    tenant_id: str
    aggregate_id: str
    ordering_key: str
    sequence_number: int
    payload: Mapping[str, Any]
    correlation_id: str
    producer: str
    schema_family: str
    schema_version: str = "1.0"
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    causation_id: UUID | None = None
    trace_id: str | None = None
    retry_count: int = 0

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.aggregate_id or not self.ordering_key:
            raise ValueError("tenant_id, aggregate_id and ordering_key are required")
        if self.sequence_number < 1:
            raise ValueError("sequence_number must start at 1")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

    def stable_bytes(self) -> bytes:
        body = {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "aggregate_id": self.aggregate_id,
            "ordering_key": self.ordering_key,
            "sequence_number": self.sequence_number,
            "schema_family": self.schema_family,
            "schema_version": self.schema_version,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "producer": self.producer,
            "occurred_at": self.occurred_at.astimezone(UTC).isoformat(),
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "trace_id": self.trace_id,
            "retry_count": self.retry_count,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


@dataclass
class OutboxRecord:
    topic: str
    envelope: EventEnvelope
    partition_key: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    published_at: datetime | None = None
    attempts: int = 0
    last_error: str | None = None

    @property
    def pending(self) -> bool:
        return self.published_at is None


@dataclass(frozen=True)
class RetryDecision:
    destination_topic: str
    delay_seconds: int
    terminal: bool


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    backoff_seconds: tuple[int, ...] = (1, 5, 30, 120)

    def decide(self, base_topic: str, attempt: int, retry_topic: str, dlq_topic: str) -> RetryDecision:
        if attempt >= self.max_attempts:
            return RetryDecision(dlq_topic, 0, True)
        index = max(0, min(attempt - 1, len(self.backoff_seconds) - 1))
        return RetryDecision(retry_topic, self.backoff_seconds[index], False)


@dataclass(frozen=True)
class ApplyResult:
    status: str
    applied_sequences: tuple[int, ...]
    high_watermark: int


class OrderedInbox:
    """Tenant/aggregate inbox that deduplicates and converges out-of-order deliveries.

    Future sequence numbers are buffered. Once the missing sequence arrives, all contiguous
    buffered events are applied in deterministic order. Event IDs are globally deduplicated
    within this inbox instance while sequence uniqueness is enforced per tenant+aggregate.
    """

    def __init__(self) -> None:
        self._high_watermarks: dict[tuple[str, str], int] = {}
        self._seen_ids: set[UUID] = set()
        self._buffer: dict[tuple[str, str], dict[int, EventEnvelope]] = {}

    def high_watermark(self, tenant_id: str, aggregate_id: str) -> int:
        return self._high_watermarks.get((tenant_id, aggregate_id), 0)

    def accept(self, event: EventEnvelope, apply: Callable[[EventEnvelope], None]) -> ApplyResult:
        key = (event.tenant_id, event.aggregate_id)
        high = self._high_watermarks.get(key, 0)
        if event.event_id in self._seen_ids or event.sequence_number <= high:
            self._seen_ids.add(event.event_id)
            return ApplyResult("duplicate", (), high)

        pending = self._buffer.setdefault(key, {})
        existing = pending.get(event.sequence_number)
        if existing is not None:
            if existing.event_id != event.event_id:
                raise ValueError("conflicting events share the same aggregate sequence number")
            return ApplyResult("duplicate", (), high)

        self._seen_ids.add(event.event_id)
        pending[event.sequence_number] = event
        if event.sequence_number > high + 1:
            return ApplyResult("buffered", (), high)

        applied: list[int] = []
        next_sequence = high + 1
        while next_sequence in pending:
            item = pending.pop(next_sequence)
            apply(item)
            applied.append(next_sequence)
            self._high_watermarks[key] = next_sequence
            next_sequence += 1
        return ApplyResult("applied", tuple(applied), self._high_watermarks[key])


@dataclass(frozen=True)
class ReplayWindow:
    topic: str
    tenant_id: str
    aggregate_id: str | None
    from_sequence: int
    requested_by: str
    reason: str
    expires_at: datetime

    @classmethod
    def bounded(
        cls,
        *,
        topic: str,
        tenant_id: str,
        requested_by: str,
        reason: str,
        from_sequence: int = 1,
        aggregate_id: str | None = None,
        ttl_minutes: int = 30,
    ) -> "ReplayWindow":
        if from_sequence < 1:
            raise ValueError("from_sequence must be positive")
        if ttl_minutes < 1 or ttl_minutes > 120:
            raise ValueError("replay window must be between 1 and 120 minutes")
        return cls(
            topic=topic,
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            from_sequence=from_sequence,
            requested_by=requested_by,
            reason=reason,
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
        )
