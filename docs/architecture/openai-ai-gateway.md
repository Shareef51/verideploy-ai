# OpenAI-first production AI architecture

## Purpose

OpenAI AI Gateway introduces the AI control boundary without implementing Model Routing Cost Policy model routing or Responses API Adapter's full Responses API feature surface. All future model use must pass through this gateway rather than instantiating provider SDK clients inside agents, routes, retrievers, or workers.

## Runtime boundary

```text
Domain service / future LangGraph node
 |
 v
AIRequest (tenant, correlation, request ID, operation, configured model)
 |
 v
AIGateway
 |-- distributed rate/budget reservation
 |-- bounded retry ownership + jitter
 |-- per-attempt telemetry
 |-- cancellation settlement
 v
AIProvider protocol
 |
 +--> OpenAIProvider (official async OpenAI SDK, SDK retries disabled)
 |
 +--> DeterministicTestProvider (default unit/contract tests)
```

The OpenAI adapter sets `max_retries=0`. VeriDeploy deliberately owns retry decisions so every attempt is observable and so non-retryable authentication, permission and validation errors cannot be retried accidentally.

## Failure taxonomy

Provider failures normalize to stable application codes:

- `authentication`
- `permission`
- `invalid_request`
- `rate_limited`
- `timeout`
- `connection`
- `provider_unavailable`
- `budget_exceeded`
- `local_rate_limit`
- `cancelled`
- `unknown`

Only failures explicitly marked retryable enter the bounded retry path.

## Rate and budget control

Development/test may use `InMemoryRequestController`. Production configuration rejects that backend and requires Redis. The Redis controller atomically reserves the estimated request cost at admission time so concurrent requests cannot all pass a stale budget check. Completion settles the reservation; terminal failure or cancellation releases it.

Model Routing Cost Policy will add model-specific pricing and replace the default estimated request cost with calculated estimates/actuals.

## Secret handling

The AI status endpoint exposes booleans such as `openai_key_configured`; it never returns the key. Redaction utilities remove OpenAI-style keys, bearer authorization values, and common secret/token/password fields before diagnostic logging or persistence.

## Scope intentionally deferred

- model-role routing and cost tables: Model Routing Cost Policy
- complete Responses API streaming/tool/cancellation contract: Responses API Adapter
- image intelligence: Image Intelligence Layer
- structured output platform: Structured Output Platform
- agent prompts and orchestration: later LangGraph milestones
