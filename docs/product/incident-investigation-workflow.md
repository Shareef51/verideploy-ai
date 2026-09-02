# Real-Time Incident Investigation Workflow

Incident Realtime Sequence establishes the durable control plane for incident investigations. It intentionally does not fabricate RCA, evidence retrieval, LangGraph planning, or agent reasoning that belong to later milestones.

## Public flow

1. The Next.js incident page sends `POST /api/v1/investigations` to NestJS with tenant, user, correlation, and idempotency headers.
2. NestJS derives a stable investigation UUID and publishes `verideploy.commands.investigation.v1` with `acks=-1`.
3. The Python investigation worker validates the Pydantic command, creates tenant-scoped durable state, and appends ordered events in the same persistence boundary.
4. Each durable event is published on `verideploy.events.investigation.v1` using the canonical event envelope.
5. NestJS consumes live Kafka events and fans them out over authenticated-header SSE.
6. On initial connection or reconnect, the gateway first replays events after `Last-Event-ID` from the authoritative Python service and then follows the live Kafka stream.
7. The browser reconciles live progress with `GET /api/v1/investigations/{id}`; frontend event state is never authoritative.

## Durable ordering

Each investigation owns a monotonic `sequence_number`. Persistence rejects skipped, duplicate, or out-of-order sequence insertion. Replays use `after_sequence`, making event delivery at-least-once while UI application is idempotent by `event_id`.

## Cancellation

`POST /api/v1/investigations/{id}/cancel` publishes a versioned cancellation command. The worker records `CANCELLING`, persists the reason, emits the transition, then records the terminal `CANCELLED` state and event. Repeated cancellation of a terminal investigation is safe.

## Milestone boundary

A successful Incident Realtime Sequence create initializes a real durable investigation runtime and leaves it `RUNNING`. Evidence ingestion, specialist execution, RCA, critic loops, and completed investigation reports are not simulated here; those capabilities are introduced by their assigned later milestones.
