# OpenTelemetry Across All Services

## Outcome
When `OTEL_ENABLED=true`, VeriDeploy has W3C Trace Context propagation across browser requests, the NestJS public API, Kafka messages, Python AI/worker processes, HTTP clients, Redis, SQLAlchemy hooks, and explicit workflow spans. OTLP traces flow through the collector into Tempo.

## Trace path
`Browser span -> NestJS HTTP span -> Kafka producer -> Kafka consumer/worker -> AI service -> LangGraph/RAG/MCP/DB/external HTTP -> emitted event`

## Production rules
- `traceparent`/`tracestate` are propagated; correlation IDs remain a separate support/debug key.
- Secrets, prompt bodies, document bodies, auth headers, cookies and API keys are never span attributes.
- Health endpoints are excluded from request tracing to control noise.
- LangSmith Integration LangSmith remains optional AI-run observability and cannot affect routing, retrieval, approvals, or decisions.
- OTLP exporter failure is non-fatal in development/test and fail-fast in staging/production Python startup.

## Services
- Web: browser `CLIENT` span and W3C propagation on gateway fetches.
- Gateway: NodeSDK auto-instruments HTTP/Express/fetch/KafkaJS and exports OTLP/gRPC.
- AI service: FastAPI, HTTPX and Redis instrumentation; helper supports SQLAlchemy and explicit spans.
- Workers: per-process tracer initialization; Kafka trace headers continue parent context.
- Collector: memory limiter + batching + resource normalization; trace export to Tempo.

## Validation gate
A trace is valid when the same W3C trace ID is visible through the gateway, asynchronous Kafka hop, Python processing and final event path. Run `python scripts/validate_opentelemetry.py`.
