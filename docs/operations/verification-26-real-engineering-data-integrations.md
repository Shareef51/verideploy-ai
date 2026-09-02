# Real Engineering Data Integrations Verification

Run the focused suite:

```bash
PYTHONPATH=src:. pytest -q tests/unit/test_engineering_integrations.py tests/unit/test_integration_api.py
```

Run the cumulative Python suite:

```bash
PYTHONPATH=src:. pytest -q
```

Key Real Engineering Data Integrations checks include GitHub Link pagination, Jira next-page-token pagination, bounded retries/rate-limit hints, per-run quotas, host and redirect allowlists, Jira Basic/Bearer auth construction, secret non-leakage, Prometheus/Grafana/Tempo/Loki time-range contracts, stable log IDs, explicit unconfigured status, private readiness authorization, and synthetic/live schema parity.

No live GitHub/Jira/observability call is required for CI. Contract tests use `httpx.MockTransport`. Production endpoints remain opt-in through environment configuration.
