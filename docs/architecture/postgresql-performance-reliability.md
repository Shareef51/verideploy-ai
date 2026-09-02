# PostgreSQL Performance and Reliability

## Scope
PostgreSQL Performance Reliability preserves the Complete RAG Operational Schema semantics while adding bounded database resource use, targeted indexes, query telemetry, migration serialization, load gates, and recovery/HA operating assumptions.

## Connection pooling and query budgets
`DatabaseManager` uses SQLAlchemy pooling with `pool_pre_ping`, bounded pool size/overflow/wait, connection recycle, and LIFO reuse for PostgreSQL. Every tenant session applies transaction-local `statement_timeout`, `lock_timeout`, and `idle_in_transaction_session_timeout` plus `app.tenant_id`. Callers can provide a validated `QueryBudget` for a narrower operation-specific budget.

## Slow-query telemetry
SQLAlchemy cursor events measure execution duration. Queries crossing `DB_SLOW_QUERY_THRESHOLD_MS` are represented by a normalized SHA-256 SQL fingerprint, operation, duration, row count, and timestamp. Bind parameter values are not recorded. `database_query_telemetry` is append-oriented and RANGE partitioned by `observed_at`; its default partition exists to prevent rejected writes between managed monthly partitions.

## Partitioning decision
Partitioning is justified only for the high-volume time-series query-telemetry stream. Existing releases, incidents, evidence, graph, and RAG tables retain their canonical identities because repartitioning them in PostgreSQL Performance Reliability would add foreign-key/RLS migration risk without measured evidence that they need partitioning. Operators can later add monthly telemetry partitions without changing application contracts.

## Index strategy
PostgreSQL Performance Reliability adds partial indexes for active incidents, investigations, ready jobs, unpublished outbox records, and pending reviews; composite indexes cover retrieval source/chunk order, graph relation/time queries, and evidence kind/time queries. These are workload-oriented rather than duplicating all existing indexes.

## Migration reliability
Online Alembic execution is serialized with a PostgreSQL advisory lock acquired through `pg_try_advisory_lock`. Acquisition is bounded by `DB_MIGRATION_LOCK_TIMEOUT_SECONDS`; failure aborts the migration rather than running concurrently.

## Explain and concurrency policy
`config/load/postgres-load.json` defines deterministic fixture volume, concurrency, and thresholds. Provisioned tests use `EXPLAIN (ANALYZE, FORMAT JSON)` and reject plans that exceed execution/cost limits or perform large sequential scans. The concurrency gate measures bounded multi-worker read latency and error rate.

## HA assumptions
Application correctness assumes one writable primary endpoint. Production HA is provided by the PostgreSQL platform (streaming/log-shipping standby, managed failover, or equivalent). The application uses `pool_pre_ping` so dead pooled connections are detected after failover. VeriDeploy does not claim synchronous multi-primary semantics.

## Backup/PITR assumptions
Production PITR requires WAL archiving plus a recoverable base backup. A backup is not considered healthy until restore verification succeeds in an isolated environment. Logical `pg_dump` remains useful for portable/schema-level recovery but is not a replacement for WAL-based PITR for low-RPO production recovery.
