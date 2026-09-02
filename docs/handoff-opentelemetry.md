# Handoff — OpenTelemetry Across All Services

## Outcome
OpenTelemetry Across All Services is complete and cumulative through Milestones 1–50. OpenTelemetry is implemented as the vendor-neutral distributed trace plane, with W3C context propagation and OTLP export to the existing collector/Tempo stack.

## Important files
- `src/verideploy/observability/telemetry.py`
- `apps/gateway/src/observability/telemetry.ts`
- `apps/web/lib/observability/browser-telemetry.ts`
- `infrastructure/observability/otel-collector.yaml`
- `infrastructure/observability/tempo.yaml`
- `docs/architecture/opentelemetry-across-all-services.md`
- `docs/decisions/ADR-0032-opentelemetry-is-the-cross-service-trace-standard.md`
- `tests/unit/test_opentelemetry.py`
- `scripts/validate_opentelemetry.py`

## Trace architecture
Browser client span -> NestJS inbound HTTP -> Kafka producer -> worker Kafka consumer -> AI/service operations -> LangGraph/RAG/MCP/data/outbound HTTP -> final event. `traceparent` and `tracestate` are the propagation standard; `x-correlation-id` remains the business/support correlation key.

## Commands
```bash
python scripts/validate_opentelemetry.py
pytest -q
docker compose up -d tempo otel-collector
```

## Actual verification
- OpenTelemetry Across All Services validation gate: PASS
- Full Python suite: 547 passed, 20 skipped, 0 failed
- Python compileall: PASS
- Regression set covering LangGraph, MCP, retrieval, frontend foundation and LangSmith: PASS

Skipped tests require an external PostgreSQL/pgvector integration runtime or the optional LangGraph package in this execution environment.

## Operational note
Python `OTEL_ENABLED` defaults to false to keep tests and offline developer commands deterministic; `.env.example` enables it for the composed application. The web and NestJS services can also be disabled with their OTel environment switches.

## Next cumulative milestone
**Evaluation Framework — Evaluation Framework Foundation**: versioned datasets, evaluators, run manifests, result storage, baseline comparison, CLI/worker execution, reproducibility metadata, and a local/CI smoke evaluation.
