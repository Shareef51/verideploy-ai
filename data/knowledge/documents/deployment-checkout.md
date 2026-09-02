# Synthetic Deployment Record: Checkout API rc3

Deployment rel-2026.08.17-rc3 targeted checkout-api in production. The release changed worker concurrency from 20 to 60 processes while leaving the configured database pool at 40 total client connections. Image digest was sha256:7b8d4f1e6d2c4f79f36c9c3ce1b9b2dfad60e9f2c5071c54d7154e50f2a11111.

The synthetic deployment started at 2026-08-17T13:57:00Z and completed at 2026-08-17T13:59:30Z. Alerting detected elevated checkout latency shortly afterward. Rollback readiness was available and the prior version rel-2026.08.16-stable remained deployable.

This record is read-only knowledge evidence. It does not authorize rollout, rollback, dispatch, merge, or other engineering-system writes.
