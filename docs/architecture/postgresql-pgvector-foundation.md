# PostgreSQL and pgvector Foundation

## Purpose

PostgreSQL pgvector Foundation establishes Alembic as the schema authority for the canonical PostgreSQL vector foundation. Application startup must not create these canonical tables. The browser and AI layers continue to depend on repositories; repositories depend on the shared `DatabaseManager`.

## Canonical PostgreSQL pgvector Foundation tables

- `tenants`
- `embedding_models`
- `vector_embeddings`

The earlier `embedding_cache` table remains a compatibility cache for the cumulative codebase. It is not the canonical pgvector store and will be retired through a later explicit data migration.

## Vector migration decision

Revision `0001_milestone12_pgvector` fixes the PostgreSQL pgvector Foundation index at 3072 dimensions for the configured `text-embedding-3-large` binding. Runtime configuration is validated against `config/vector-index.json`. Changing model or dimensions requires a new migration, a new index version, and re-embedding; the existing HNSW index is never reused with incompatible dimensions.

## Indexing

`vector_embeddings.embedding` is PostgreSQL `vector(3072)`. Cosine nearest-neighbor access uses an HNSW index with `vector_cosine_ops`, `m=16`, and `ef_construction=64`. Exact parameter changes must be migration-controlled and benchmarked rather than altered ad hoc.

## Tenant isolation

Every repository query includes `tenant_id` explicitly. A transaction-local `app.tenant_id` setting activates PostgreSQL RLS as defense in depth. `vector_embeddings` uses both `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`; inserts/updates are also checked by the policy. RLS is never treated as the only tenant boundary.

## Reliability

The shared engine uses `pool_pre_ping`, bounded pool size/overflow, and per-transaction statement timeout. Alembic owns upgrade/downgrade. Backup/restore procedure is documented separately.
