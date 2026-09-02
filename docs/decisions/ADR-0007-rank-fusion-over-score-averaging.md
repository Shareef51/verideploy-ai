# ADR-0007 — Use Reciprocal Rank Fusion for lexical + dense retrieval

## Status
Accepted

## Decision
Use Reciprocal Rank Fusion (RRF) as the authoritative hybrid ranking mechanism. Keep per-channel normalized scores only for diagnostics and explainability.

## Rationale
PostgreSQL text-search relevance and pgvector cosine distance are not calibrated to the same numeric scale. Averaging them would create an unstable, corpus-dependent score contract. RRF combines ordinal evidence, is deterministic, and makes each contribution reconstructable.

## Consequences
- Fusion is insensitive to arbitrary raw-score scale differences.
- Ranking decisions remain auditable.
- Later rerankers can operate on the fused candidate set without changing the Hybrid Retrieval channel contracts.
