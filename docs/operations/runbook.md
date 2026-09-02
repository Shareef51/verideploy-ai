# Operations Runbook

## Gateway not ready
1. Check `/api/v1/health/live` to distinguish process death from dependency readiness.
2. Inspect gateway logs by correlation ID.
3. Confirm AI service liveness and Compose dependency state.
4. Restart only the failing service; do not wipe data volumes as a first response.

## AI service not ready
1. Check `/health/live`.
2. Validate environment parsing without printing secret values.
3. Confirm the service is reachable only inside the trusted network.

## Worker shutdown
Workers trap SIGINT/SIGTERM and stop through a cooperative event. Future consumers must finish/abandon work according to idempotency and lease policy before exit.

## Data safety
Do not use `docker compose down -v` during ordinary troubleshooting because it deletes local persistent volumes.
