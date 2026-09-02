# Five-Layer Guardrails

Five Layer Guardrails introduces a single versioned guardrail policy and enforcement contract across input, retrieval, tool/MCP, output, and operational boundaries. The policy is hashed for reproducibility and every violation carries a control ID, policy version, correlation ID, trace ID, span ID, action, and safe metadata.

## Enforcement layers

1. **Input** — payload-size ceiling, prompt-injection detection, tenant-context mismatch detection, safe redaction.
2. **Retrieval** — tenant boundary enforcement plus quarantine of instruction-like content embedded in retrieved evidence. Retrieved content remains data, never instructions.
3. **Tool/MCP** — role allowlists, tenant binding, injection screening, mandatory dry-run and human approval for consequential operations.
4. **Output** — sensitive-field/PII redaction, abstention on unsupported material claims, and stable citation requirements.
5. **Operational** — retry ceilings, per-request cost budget, concurrency ceilings, per-tenant operation rate limits, and OTel guardrail events.

## Policy and telemetry

`config/guardrails/policy.json` is the canonical policy. `GuardrailPolicy.sha256` lets historical traces resolve the exact policy content. `GuardrailTelemetry` records bounded in-memory counters/events and adds `guardrail.violation` events to the active OpenTelemetry span.

## Red-team gate

`evals/fixtures/guardrails/redteam.json` covers user prompts, WebSocket-style payloads, Kafka/event payloads, poisoned documents, cross-tenant retrieval, consequential MCP actions, unsupported output claims, operational retry abuse, and legitimate traffic. CI executes `scripts/benchmark_guardrails.py`; every fixture must match its expected allow/warn/deny/abstain result.

## Safe error behavior

Callers may inspect `GuardrailDecision`; enforcement boundaries use `GuardrailEngine.enforce()`, which raises the generic `GuardrailDenied` exception without echoing malicious payloads or secrets. Detailed evidence remains in internal telemetry.
