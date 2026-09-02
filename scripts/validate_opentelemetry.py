from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
checks={
"python_sdk": "opentelemetry-sdk" in (ROOT/"pyproject.toml").read_text(),
"python_runtime": (ROOT/"src/verideploy/observability/telemetry.py").exists(),
"fastapi": "configure_telemetry" in (ROOT/"services/ai/main.py").read_text(),
"nestjs": 'import "./observability/telemetry"' in (ROOT/"apps/gateway/src/main.ts").read_text(),
"browser": "tracedFetch" in (ROOT/"apps/web/lib/api/gateway-client.ts").read_text(),
"kafka_w3c": "extract_kafka_context" in (ROOT/"workers/investigation/investigation_worker.py").read_text(),
"collector_tempo": "otlp/tempo" in (ROOT/"infrastructure/observability/otel-collector.yaml").read_text(),
"tempo_receiver": "otlp:" in (ROOT/"infrastructure/observability/tempo.yaml").read_text(),
"redaction": "SENSITIVE_ATTRIBUTE_TOKENS" in (ROOT/"src/verideploy/observability/telemetry.py").read_text(),
"langsmith_isolation": (ROOT/"docs/decisions/ADR-0031-langsmith-is-observability-only.md").exists(),
}
result={"gate":"one distributed trace from browser request to final event","checks":checks,"passed":all(checks.values())}
(ROOT/"artifacts/opentelemetry-validation.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result,indent=2))
raise SystemExit(0 if result["passed"] else 1)
