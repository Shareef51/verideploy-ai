# LangGraph State Reducers Verification

Run:

```bash
PYTHONPATH=src:. pytest -q tests/unit/test_langgraph_state_reducers.py
make langgraph-state-validate
PYTHONPATH=src:. pytest -q
```

With a provisioned PostgreSQL database, set `TEST_POSTGRES_URL` and run `tests/integration/test_postgres_saved_state.py`. That integration test migrates to head, persists a state snapshot, verifies cross-tenant invisibility, and checks that direct SQL mutation is rejected.

Offline Alembic verification must include upgrade through `0021_milestone39_langgraph_state_reducers` and downgrade `0021 → 0020`.

The LangGraph State Reducers acceptance gate is satisfied only when a legacy active investigation upgrades to the current schema while retaining investigation/run/correlation identity, saved node output, approval references, and replay continuity. Unit/replay tests are authoritative for this environment; live PostgreSQL trigger execution must not be reported as passed unless `TEST_POSTGRES_URL` is configured.
