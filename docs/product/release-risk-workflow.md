# Release-Risk Workflow

Release Risk Sequence introduces an auditable release-risk lifecycle without prematurely adding LLM judgment. The public browser path remains Next.js → NestJS. NestJS validates public request shape and required tenant/user/idempotency headers, then invokes the private AI-control boundary. The Python release-risk service persists the request and computes a deterministic policy score whose factor breakdown is stored with the assessment.

## Lifecycle

`ACCEPTED → QUEUED/RUNNING → COMPLETED | FAILED | CANCELLED`

The current private HTTP adapter executes the worker step immediately after durable acceptance so local mode remains runnable without Kafka. The production Kafka worker implements the same domain service and consumes `verideploy.commands.release-risk.v1`; deployment can switch transport without changing scoring or persistence semantics.

## Idempotency

The unique business key is `(tenant_id, idempotency_key)`. Retries return the same assessment instead of creating duplicate work. Completed duplicate commands publish the existing result.

## Risk policy

The v1 policy uses transparent factors: change blast radius, large change set, failed workflows, database migration/rollback readiness, recent incidents, coverage regression, critical security findings, and deployment-window risk. Critical security findings, repeated CI failures, and unverified migration rollback paths impose score floors. The LLM is not authoritative for Release Risk Sequence scoring.

## Security boundary

The Python endpoint requires the trusted gateway service identity header and tenant-scoped reads. This is a Release Risk Sequence service-boundary mechanism, not the final production service-auth design; full workload identity is scheduled for the security milestone.
