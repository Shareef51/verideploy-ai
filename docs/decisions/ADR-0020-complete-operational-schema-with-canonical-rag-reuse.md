# ADR-0020 — Complete operational schema while reusing canonical RAG tables

## Decision
Keep Hybrid Retrieval documents/chunks, Visual Document Retrieval visual pages/indexes, and Supervisor Planner Agent Contracts agent runs as the canonical tables. Add only missing Complete RAG Operational Schema operational tables and expose one authoritative schema catalog.

## Rationale
Duplicating RAG or agent-run storage would create inconsistent truth and migrations. Complete RAG Operational Schema is a completeness milestone, not a storage rewrite. Lifecycle state changes are guarded in application code and PostgreSQL; tenant identity is enforced by RLS plus link-validation triggers.
