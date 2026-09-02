# Kafka Event-Driven Architecture

Kafka Event Driven Architecture finalizes Kafka as the durable asynchronous backbone. Kafka remains authoritative for commands/events; Redis is used only for low-latency NestJS fan-out to connected browser sessions.

## Topic and ordering contract

`config/kafka/topics.json` is the canonical registry. Every business topic is versioned, has explicit partition/replication/retention settings, a schema family, and backward-compatibility policy. Producers use `tenant_id:aggregate_id` as the stable ordering key so all state transitions for one aggregate remain on one partition.

The canonical event envelope carries event ID, tenant, aggregate, ordering key, monotonically increasing sequence number, schema family/version, correlation/trace identity, causation, retry count, producer, timestamp, and payload.

## Transactional outbox/inbox

Migration `0027_milestone65_kafka_event_architecture.py` adds tenant-RLS-protected outbox, inbox, and replay-request tables. Business writes and outbox inserts belong in the same database transaction. Publisher workers mark rows published only after Kafka acknowledgement. Consumers insert inbox identity before applying side effects so redelivery is idempotent.

The inbox contract uses `(consumer_group,event_id)` for duplicate suppression and `(consumer_group,tenant_id,aggregate_id,sequence_number)` to prevent conflicting sequence application.

## Out-of-order convergence

`OrderedInbox` buffers future sequence numbers and applies only contiguous ranges after gaps arrive. A replay or duplicate cannot regress the high watermark. Tenant and aggregate scopes are independent.

## Retry, DLQ and replay

Transient failures move through `verideploy.retry.platform.v1` using bounded backoff. Exhausted failures go to `verideploy.dlq.platform.v1`. Replay requests are tenant-scoped, reasoned, time-bounded, auditable, and may target an aggregate/from-sequence range. Replay does not bypass inbox idempotency.

## Consumer scaling

Partitions are the scaling unit. Consumer instances share stable functional group IDs. Per-instance groups are reserved for browser fan-out workloads that intentionally require every gateway replica to receive live events. Business side-effect consumers use shared groups.

## NestJS/Redis WebSocket fan-out

Gateway replicas publish validated Kafka events to tenant-specific Redis channels. `EventFanoutService` subscribes through Redis so every gateway replica can deliver tenant-filtered events to local WebSocket clients at `/ws/events`. Redis is not an event source of truth; reconnect/reconciliation still reads persisted authoritative state.

## Gate

Run:

```bash
PYTHONPATH=src python scripts/benchmark_kafka_architecture.py
PYTHONPATH=src python -m pytest -q tests/events/test_kafka_event_driven_architecture.py
```

The benchmark deliberately sends 100 unique state transitions out of order and then redelivers all 100. Exactly 100 transitions must apply, in sequence, and terminal retry exhaustion must route to the DLQ.
