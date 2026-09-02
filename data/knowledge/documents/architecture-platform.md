# VeriDeploy Synthetic Platform Architecture

This synthetic architecture document defines the release-assurance control plane used by the demonstration corpus. The public browser communicates with the Next.js application, which calls the NestJS gateway. Private Python AI services are not directly reachable by browsers. Kafka carries commands and events, PostgreSQL stores tenant-scoped operational state and pgvector embeddings, Redis provides short-lived coordination state, and MinIO stores uploaded evidence objects.

The checkout-api service depends on postgres-primary, redis-cache, and kafka-orders. Production releases are admitted only after deterministic release-risk checks complete. Incident investigations may combine runtime metrics, logs, traces, deployment metadata, runbooks, historical postmortems, screenshots, and operator evidence. Human approval remains mandatory for consequential external writes.

Availability objective: checkout-api monthly SLO is 99.95 percent. A release that introduces database saturation, error-rate regression, or rollback-readiness failure is treated as a release-assurance risk rather than an automatically remediated condition.
