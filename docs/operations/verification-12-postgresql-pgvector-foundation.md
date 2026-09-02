# PostgreSQL and pgvector Foundation Verification

Date: 2026-08-17
Repository version: 0.12.0

## Executed successfully in this environment

- Cumulative pytest: 117 passed, 2 skipped.
- The 2 skipped tests are real PostgreSQL/pgvector integration tests guarded by TEST_POSTGRES_URL.
- PostgreSQL pgvector Foundation focused unit/config/Compose checks passed.
- Python compileall passed for src, services, workers, scripts, and tests.
- Alembic offline upgrade SQL generation passed.
- Alembic offline downgrade SQL generation passed.
- Generated upgrade DDL contains CREATE EXTENSION vector, vector(3072), cosine HNSW, ENABLE/FORCE RLS, and the tenant isolation policy.
- Generated downgrade DDL drops vector_embeddings, embedding_models, and tenants while retaining the shared vector extension.
- FastAPI liveness/readiness smoke passed and both report version 0.12.0.
- Cumulative contract validation passed.
- config/vector-index.json and docker-compose.yml parsed successfully.
- 36 TypeScript/TSX source files syntax-transpiled successfully.
- PostgreSQL pgvector Foundation production-path TODO/FIXME/fake-success/placeholder scan passed.
- Static key/private-key pattern scan passed.

## Not executed / not claimed as passed

- Live PostgreSQL migration upgrade/downgrade was not executed because TEST_POSTGRES_URL is not configured and Docker Engine is unavailable.
- Live pgvector HNSW query-plan assertion and RLS tenant-isolation integration tests were therefore skipped, not passed.
- pg_dump/pg_restore recovery drill was not executed; the runbook and post-restore verifier are included for a provisioned environment.
- Ruff and MyPy executables are unavailable in this runtime.
- Full pnpm dependency-aware builds/tests were not executed. TypeScript syntax transpilation was executed instead.
- uv.lock could not be generated offline because inherited dependencies such as aiokafka are not present in the local uv cache; no lock success is claimed.

## Provisioned-environment gates

Run:

1. make migrate
2. make db-check
3. TEST_POSTGRES_URL=<dedicated-postgres-url> pytest -q tests/integration/test_postgres_pgvector.py
4. make db-backup
5. Restore the dump into a clean database.
6. Point DATABASE_URL at the restored database and run make db-restore-verify.
7. make lint && make typecheck && make test
