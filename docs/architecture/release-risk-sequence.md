# Release-Risk Sequence

1. The authenticated browser submits release metadata and policy signals to `POST /api/v1/releases/risk-assessments`.
2. NestJS validates the request and required identity/idempotency headers.
3. The gateway derives a stable UUID from `(tenant_id, idempotency_key)` so request retries address the same assessment.
4. The gateway publishes a schema-versioned command to `verideploy.commands.release-risk.v1` with Kafka `acks=-1`.
5. The Python release-risk worker validates the command using Pydantic, persists or recovers the assessment, and emits a started event.
6. The deterministic `release-risk-v1.0.0` engine calculates factor points, score floors, level, deployment decision, recommendations, confidence, and human-review requirement.
7. The worker persists the terminal result and emits `release.risk.completed` on `verideploy.events.release-risk.v1`.
8. The UI requests the authoritative status through NestJS; NestJS reads through the private Python service with tenant scope.
9. The UI stops polling on `COMPLETED`, `FAILED`, or `CANCELLED`.

The LLM does not author the numeric release score in Release Risk Sequence. This keeps the decision auditable and follows the master architecture requirement that model-derived reasoning must not secretly become the authoritative score.
