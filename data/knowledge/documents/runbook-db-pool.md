# Checkout Database Pool Saturation Runbook

Use this synthetic runbook when checkout-api latency rises together with PostgreSQL connection utilization. Confirm the active incident window and compare it with the immediately preceding baseline. Inspect application pool utilization, database active connections, queue wait duration, request latency, and recent deployment changes.

Do not restart the database as a first action. First determine whether the application pool is exhausted, the database connection limit changed, or a deployment introduced a connection leak. Read-only validation should include current pool size, checked-out connections, waiting requests, and transaction duration. If rollback is recommended, require the normal human approval path before any deployment mutation.

Resolution evidence should include the metric or trace showing saturation, the deployment or configuration change associated with the onset, and a post-change verification window showing queueing and latency returning toward baseline.
