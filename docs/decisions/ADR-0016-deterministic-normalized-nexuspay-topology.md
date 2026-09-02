# ADR-0016 — Deterministic normalized NexusPay topology

## Decision

Represent the NexusPay Service Topology synthetic company topology as a deterministic, normalized, tenant-scoped graph with stable UUIDv5 identities and a canonical seed SHA-256. Persist the exact validated snapshot to PostgreSQL and expose it through the existing Next.js → NestJS → private FastAPI boundary.

## Why

Later synthetic incidents, release histories, evidence, and RCA benchmarks require stable service identities and dependency relationships. Frontend-only JSON would not provide durable referential integrity; database-only seed logic would be harder to review and reproduce. The checked-in generated snapshot plus deterministic generator provides both reviewability and persistence.

## Consequences

Seed changes are explicit data-contract changes. Topology invariants must pass before persistence. All tables enforce tenant RLS. The application call graph is kept acyclic; telemetry edges are excluded from that cycle check because they model observability export rather than synchronous business dependency.
