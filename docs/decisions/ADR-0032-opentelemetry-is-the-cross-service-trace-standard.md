# ADR-0032: OpenTelemetry is the cross-service trace standard

Status: Accepted

## Decision
Use OpenTelemetry and W3C Trace Context as the vendor-neutral distributed tracing plane across all VeriDeploy services. Tempo is the default local trace backend. LangSmith remains a separate optional AI observability sink.

## Consequences
Every network boundary must preserve trace context, telemetry must redact sensitive content, and application correctness must not depend on the telemetry backend.
