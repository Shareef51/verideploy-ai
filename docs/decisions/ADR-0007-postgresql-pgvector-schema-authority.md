# ADR-0007 — PostgreSQL/pgvector Schema Authority

**Status:** Accepted

## Decision

Use Alembic migrations as the schema authority for canonical PostgreSQL tables. Use PostgreSQL pgvector for semantic vectors, HNSW cosine indexing for the PostgreSQL pgvector Foundation vector index, explicit tenant filters in repositories, and RLS as a second isolation layer.

Runtime `metadata.create_all()` is not permitted for canonical PostgreSQL pgvector Foundation tables. Temporary cumulative tables from earlier milestones remain until explicit later migrations replace them.

Embedding dimension is a migration/index decision, not an arbitrary runtime switch. A model/dimension change requires re-embedding into a new compatible index.
