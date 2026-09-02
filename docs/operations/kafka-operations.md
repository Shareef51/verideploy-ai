# Kafka Operations Runbook

## Readiness and lag
Track consumer lag per consumer group and tenant-safe ordering key. Page the platform owner when lag exceeds the Production Operations Checkpoint alert threshold. Durable Kafka state remains authoritative; Redis/WebSocket fan-out is never the source of truth.

## Retry and DLQ
Use the bounded retry topics defined in `config/kafka/topics.json`. Do not replay a DLQ blindly. Record tenant, aggregate, original event ID, schema family/version, reason, operator, and replay correlation ID. Replays must remain idempotent through inbox deduplication.

## Broker/consumer failure
Scale consumers only after confirming partition ownership and ordering constraints. During broker recovery, preserve outbox records and do not bypass the transactional publication boundary.

## Replay safety
Replay by tenant and aggregate scope, enforce expiry/reason, and verify the authoritative watermark converges before considering the incident resolved.
