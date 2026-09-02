# PostgreSQL Performance Reliability Verification

Static/focused verification covers query budgets, pooling, slow-query fingerprints, explain-plan policy, targeted indexes, partitioned telemetry/RLS, migration locking, configuration propagation, and load thresholds. The live PostgreSQL gate in `tests/integration/test_postgres_performance_live.py` is conditional on `TEST_POSTGRES_URL` and must not be reported as passed when skipped.

Run:

```bash
PYTHONPATH=src:. pytest -q tests/unit/test_postgres_performance.py
PYTHONPATH=src:. pytest -q tests/integration/test_postgres_performance_live.py
make postgres-performance-validate
PYTHONPATH=src:. pytest -q
```

Provisioned acceptance uses EXPLAIN ANALYZE JSON and concurrent tenant-scoped reads against thresholds in `config/load/postgres-load.json`.
