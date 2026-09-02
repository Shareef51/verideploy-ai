# Model Routing and Cost Policy

## Purpose

Model Routing Cost Policy makes model selection a deterministic platform policy rather than a caller decision. Application code asks for a workload; the model router selects a logical role (`fast`, `standard`, or `reasoning`), resolves the configured model, records why it selected that route, and applies bounded retry/fallback, concurrency, budget, and cost policy.

## Default workload routing

| Workload | Role |
| --- | --- |
| intent classification | fast |
| query rewriting | fast |
| metadata extraction | fast |
| ordinary tool selection | fast |
| standard RAG response | standard |
| release-risk assessment | standard |
| evidence fusion | standard |
| executive report | standard |
| complex RCA | reasoning |
| contradiction resolution | reasoning |

Unknown workloads use the configured default role (`standard`). `AI_OPERATION_ROLE_OVERRIDES_JSON` can override an operation without changing application code.

## Model bindings

Model identifiers are not embedded in routing logic. Deployment configuration supplies:

- `OPENAI_FAST_MODEL`
- `OPENAI_STANDARD_MODEL`
- `OPENAI_REASONING_MODEL`
- optional comma-separated fallback chains for each role

Staging and production configuration fails validation when any logical role is unresolved.

## Fallback policy

A fallback is only considered after the current model exhausts its bounded retries and the normalized error is one of: rate limited, provider unavailable, timeout, or connection failure. Authentication, permission, malformed request, and other non-retryable errors never trigger a different model. This prevents a fallback from hiding configuration or authorization failures.

## Cost policy

`config/model-pricing.json` is a versioned operator-maintained catalog. It carries `catalog_version`, `effective_at`, `source`, and per-model input/output token prices. No pricing values are hard-coded into Python routing logic.

Before execution, the gateway reserves a conservative maximum token cost using the selected model. After success, it settles against provider-reported input/output token usage. If usage or pricing is unavailable, production rejects unpriced configured models unless `AI_ALLOW_UNPRICED_MODELS=true` is an explicit operator decision.

The repository ships a dated catalog for the current official GPT-5.6 Sol/Terra/Luna model IDs verified on 2026-08-16. It is configuration, not routing code. Before every staging/production promotion, operators must re-verify the catalog against official OpenAI model/pricing documentation and update `effective_at`/`catalog_version` when prices or model IDs change. Models outside the catalog are rejected in production by default.

## Concurrency

Per-role semaphores prevent expensive reasoning traffic from consuming all local worker capacity:

- `AI_FAST_CONCURRENCY`
- `AI_STANDARD_CONCURRENCY`
- `AI_REASONING_CONCURRENCY`

Distributed per-tenant request and monthly budget admission remains owned by the OpenAI AI Gateway `RequestController` (Redis in production).

## Audit

Each attempted routed model produces a `ModelRoutingAuditRecord` with:

- request, tenant, and correlation IDs
- operation
- logical role
- resolved model
- routing reason
- fallback index
- whether policy override participated
- estimated and actual cost
- retry count
- latency
- outcome

LLMOps Data Platform will persist this contract into the LLMOps data platform. Model Routing Cost Policy uses a deterministic sink abstraction so the routing core is already production-boundary compatible.
