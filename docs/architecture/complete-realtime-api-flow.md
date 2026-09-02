# Complete Real-Time API Flow

Complete Realtime API Flow closes the production path for release-risk and incident-RCA workflows.

`Browser -> NestJS -> Kafka command -> Python worker -> LangGraph workflow boundary -> persistence -> Kafka event -> Redis fan-out -> NestJS WebSocket/SSE -> browser reconciliation`

## Authoritative-state rule
Live events accelerate the UI but never replace persisted state. A reconnect fetches the authoritative snapshot/high-watermark, replays any missing events, deduplicates repeated sequence numbers, and renders the snapshot only after convergence.

## Incident RCA completion
The incident worker now moves beyond runtime initialization and emits evidence links with stable citation IDs, hypothesis updates, RCA/critic output, an audit event, and a terminal `COMPLETED` transition. All persisted investigation events are strictly sequenced.

## Failure/retry behavior
Kafka commands remain idempotent; redelivery returns/replays existing state. Missing live events are recovered from persisted event replay. Duplicate events are ignored by sequence. Gaps prevent convergence until replay supplies the missing sequence.

## Gate
End-to-end tests assert terminal authoritative state, ordered events, citations, audit presence, and final UI convergence for both workflows without paid model calls.
