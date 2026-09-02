# ADR-0029 — Lease-backed long-running workflow durability

## Decision
Use database-backed leases plus idempotent logical step rows and append-only durability events around the existing LangGraph checkpoint runtime.

## Why
Long-running investigations can outlive worker processes. Process-local locks or cancellation flags do not survive crashes. A database lease provides recoverable ownership, while stable idempotency keys prevent duplicated external writes after restart.

## Safety properties
1. One non-expired owner controls a run at a time.
2. Heartbeats are compare-and-swap and stale versions fail.
3. Expired ownership can be reclaimed without changing run/thread identity.
4. Completed idempotent steps cannot transition back to a non-terminal state.
5. Human-approval waits and cancelled/completed runs are never auto-recovered.
6. Durability events are append-only and tenant isolated.
7. Operational replay is read-only and deterministic.

## Rejected alternatives
- In-memory lease ownership: lost on process death.
- Kafka consumer ownership alone: insufficient for durable graph/run semantics and side-effect idempotency.
- A second workflow engine/table duplicating LangGraph checkpoints: creates conflicting state authorities.
