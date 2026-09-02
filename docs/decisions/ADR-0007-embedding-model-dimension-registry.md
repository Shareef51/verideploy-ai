# ADR-0007 — Embedding model and dimension registry

- Status: Accepted
- Milestone: 11

## Decision

Treat `(embedding model, dimensions, registry version)` as an explicit data/index contract. Do not infer dimensions from the first provider response and do not permit silent dimension changes under the same registered model binding.

## Why

Vector stores require fixed dimensionality. Silent drift can make indexes unusable, produce runtime insert failures, or—worse—mix semantically incompatible vectors. Model upgrades therefore require a controlled re-embedding migration.

## Consequences

- Production configuration declares `OPENAI_EMBEDDING_MODEL` and `OPENAI_EMBEDDING_DIMENSIONS`.
- Every returned vector is dimension-checked before persistence.
- Existing cached vectors remain addressable by model/dimension/version.
- Re-embedding is explicit and auditable.
- PostgreSQL pgvector Foundation may bind this contract to pgvector schema/index migrations without changing Embedding Pipeline callers.
