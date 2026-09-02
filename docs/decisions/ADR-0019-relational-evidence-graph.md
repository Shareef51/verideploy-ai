# ADR-0019 — Use PostgreSQL as the Evidence Graph evidence graph index

## Decision
Store evidence-graph vertices and edges in normalized PostgreSQL tables with typed relationships, temporal metadata, tenant RLS, and bounded recursive CTE traversal.

## Why
The project already treats PostgreSQL as its durable system of record. Evidence Graph does not require graph-database-specific algorithms, so introducing Neo4j or another graph store would duplicate tenancy, backup, observability, and consistency boundaries. Relational adjacency indexes and recursive SQL satisfy the required PR-to-service-to-incident-to-cause traversal while keeping evidence references transactionally close to Immutable Evidence Model immutable records.

## Consequences
Traversal depth is deliberately bounded. More advanced graph analytics can be introduced later only if evaluation proves the relational model insufficient. Every edge remains typed, tenant-scoped, and time-qualified.
