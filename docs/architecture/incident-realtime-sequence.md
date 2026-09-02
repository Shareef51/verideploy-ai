# Incident Real-Time Sequence

```text
Next.js
 | POST /investigations
 v
NestJS gateway
 | durable command (Kafka, acks=-1)
 v
verideploy.commands.investigation.v1
 v
Python investigation worker
 | validate -> create/idempotency -> persist state -> append sequenced events
 +-------------------------------> PostgreSQL
 |
 +--> verideploy.events.investigation.v1
 |
 v
 NestJS Kafka consumer
 |
 +--> SSE live stream
 |
Reconnect ----+--> replay after Last-Event-ID from private AI API -> PostgreSQL
 |
 v
Next.js merges by event_id and sequence, then refreshes authoritative REST snapshot.
```

The same model applies to cancellation through `verideploy.commands.investigation-cancel.v1`.
