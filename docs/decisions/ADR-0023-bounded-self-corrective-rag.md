# ADR-0023 — Bounded self-corrective RAG

## Decision
Use a deterministic bounded controller around the existing authorized retrieval pipeline. Query correction may change the query or relax requested metadata, but it may never mutate trusted authorization. Evidence sufficiency is determined by a transparent rubric using top rerank score, source count, and usable parent context. External search is policy/permission/provider gated and remains supplemental.

## Consequences
The system cannot loop indefinitely, cannot silently widen tenant or permission scope, and cannot turn insufficient evidence into an unqualified answer. Corrective history is persisted append-only for audit and replay.
