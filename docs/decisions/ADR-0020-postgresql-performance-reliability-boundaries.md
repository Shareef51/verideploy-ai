# ADR-0020 — PostgreSQL Performance and Reliability Boundaries

## Decision
Use targeted workload indexes, pooled connections with transaction-local budgets, fingerprint-only slow-query telemetry, advisory-locked migrations, and partition only the append-heavy query telemetry stream in PostgreSQL Performance Reliability.

## Rationale
Broad repartitioning of mature tenant/RLS tables would create migration and foreign-key risk without benchmark evidence. Reliability controls should fail closed: queries time out, lock waits are bounded, migration races abort, and explain/concurrency thresholds are explicit.

## Consequences
Production deployments must configure and test HA, WAL archive retention, base backups, restore/PITR drills, monitoring, and monthly telemetry partitions. PostgreSQL Performance Reliability provides application contracts and readiness gates but does not fabricate a standby or backup service inside the application.
