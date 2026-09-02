# Incident Response Runbook

1. Declare severity and incident commander; capture correlation/trace IDs and affected tenants without copying secrets.
2. Verify gateway/AI readiness, Kafka lag/DLQ, Postgres/Redis/object-store health, OIDC discovery, and SLO burn alerts.
3. Prefer rollback/canary controls already documented by Kubernetes Scalability Resilience. Consequential changes require human approval and dry-run evidence.
4. Preserve append-only audit events and evidence IDs. Never edit audit history or bypass tenant isolation during incident response.
5. For data-risk incidents, stop writes if required, verify backup freshness, restore into an isolated target, then run `scripts/verify_database_restore.py` before promotion.
6. For Kafka incidents, follow `docs/operations/kafka-operations.md`; replay only scoped, idempotent events.
7. Close only after service health, SLOs, consumer watermarks, audit continuity, and user-visible reconciliation are confirmed.
8. Produce a post-incident RCA with cited evidence and tracked corrective actions.
