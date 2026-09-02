# Real-Time Incident Investigation Screen

Real Time Incident Investigation Screen projects the durable investigation journal into a server-authoritative UI view. The browser never invents RCA state and never calls Python directly.

## Convergence model

1. Load `/api/v1/investigations/{id}/view` from NestJS.
2. Subscribe to `/api/v1/investigations/{id}/stream` using the last authoritative sequence.
3. Apply only contiguous events through the typed reducer.
4. On a gap or reconnect, replay `/events?after_sequence=N`.
5. Fetch the authoritative `/view` projection after replay; server state wins if there is any disagreement.
6. Cancellation remains a durable Kafka command and terminal state comes from the authoritative journal.

The projection contains timeline, hypotheses, root-cause state, alternative causes, and evidence relationships. Its SHA-256 is deterministic over the authoritative projection and is suitable for convergence diagnostics.
