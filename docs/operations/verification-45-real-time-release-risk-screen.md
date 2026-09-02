# Real Time Release Risk Screen Verification

Run `make release-risk-screen-validate` and `pytest -q tests/unit/test_release_risk_screen.py`. The cumulative suite must remain green. Verify the gateway public OpenAPI exposes release assessment list and SSE routes but no `/internal/v1` paths. Alembic `0024` must upgrade/downgrade cleanly.
