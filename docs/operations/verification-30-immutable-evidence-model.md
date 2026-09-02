# Immutable Evidence Model Verification

Run:

```bash
PYTHONPATH=src:. pytest -q tests/unit/test_immutable_evidence.py
PYTHONPATH=src:. pytest -q
python -m compileall -q src services
```

With `TEST_POSTGRES_URL`, the Immutable Evidence Model integration test migrates PostgreSQL to head, writes source/derived/versioned evidence, verifies lineage under tenant RLS, and confirms direct SQL UPDATE is rejected by the database immutability trigger.

Offline Alembic verification must contain the immutable mutation triggers, forced RLS, parent-tenant trigger, and deferred lineage constraint. No live PostgreSQL result may be claimed when `TEST_POSTGRES_URL` is unavailable.
