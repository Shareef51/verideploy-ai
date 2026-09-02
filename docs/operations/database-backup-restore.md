# Database Backup and Restore Runbook

## Backup

For the local PostgreSQL service:

```bash
docker compose exec -T postgres pg_dump -U verideploy -d verideploy -Fc > verideploy.dump
```

Record the application version, Alembic revision, PostgreSQL version, pgvector extension version, and SHA-256 of the dump next to the backup. Store production backups in encrypted managed storage with retention and access controls.

## Restore drill

Restore into a clean database rather than overwriting the only copy:

```bash
createdb verideploy_restore
pg_restore --clean --if-exists --no-owner --dbname=verideploy_restore verideploy.dump
```

Then verify:

1. `alembic current` reports the expected revision.
2. `SELECT extversion FROM pg_extension WHERE extname='vector';` succeeds.
3. `ix_vector_embeddings_hnsw_cosine` exists.
4. RLS is enabled and forced on `vector_embeddings`.
5. Tenant A cannot read Tenant B vectors.
6. Sample vector counts and content hashes match the backup manifest.
7. A nearest-neighbor smoke query succeeds.

Production recovery must use provider-supported PITR/backup facilities in addition to logical dumps; this runbook defines the application-level verification contract.
