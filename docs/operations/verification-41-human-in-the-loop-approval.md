# Human in the Loop Approval Verification

Run:

```bash
make human-approval-validate
pytest -q tests/unit/test_human_approval.py
pytest -q
```

When a PostgreSQL test database is available:

```bash
TEST_POSTGRES_URL=postgresql+psycopg://... pytest -q tests/integration/test_postgres_human_approval.py
```

The live PostgreSQL test verifies migration-to-head, RLS isolation, row-lock/version concurrency, a single terminal audit event, append-only audit history, and rejection of a naked `approved` SQL update without a matching signed event.

## Operational checks
- Monitor queue age and approvals approaching `expires_at`.
- Rotate the HMAC signing key through secrets management; do not store it in approval state.
- Treat HTTP 409 as a stale/concurrent review indication and refresh the current request before another action.
- A rejected, expired, cancelled, changes-requested, or pending approval must never authorize a production action.
- Reviewer delegation remains subject to policy and role checks.
