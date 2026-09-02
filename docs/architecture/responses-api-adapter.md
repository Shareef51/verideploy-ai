# OpenAI Responses API Adapter

## Purpose

Responses API Adapter turns the OpenAI AI Gateway and Model Routing/Cost Policy provider boundary into a complete OpenAI Responses API transport while keeping OpenAI-specific event types out of VeriDeploy business code.

## Production boundary

```text
agent / graph / domain service
 -> AIRequest
 -> AIGateway
 -> routing + concurrency + budget
 -> OpenAIProvider
 -> POST /v1/responses
 -> Responses stream events
 -> cancel response
 -> normalized AIResult / AIStreamEvent
 -> tenant-scoped response snapshot
```

The browser still never calls this private Python service directly.

## Typed inputs

`AIRequest` supports plain text and typed Responses input items:

- message input (`user`, `assistant`, `system`, `developer`);
- function-call output for continuation after a tool execution;
- instructions;
- previous response ID;
- function tools and constrained tool choice;
- provider-side store flag;
- background flag;
- maximum output tokens and metadata.

Structured Output Platform owns structured-output schemas and repair policy; Responses API Adapter does not implement that future scope.

## Unified output contract

Both non-streaming and streaming requests terminate in the same `AIResult` contract containing:

- VeriDeploy request ID;
- provider request ID;
- provider response ID;
- logical role and resolved model after gateway enrichment;
- text output;
- normalized function tool calls;
- response status;
- token usage including cached-input and reasoning-token details when present;
- latency, attempts, fallback index, estimated cost, and actual cost.

Streaming adds normalized `AIStreamEvent` envelopes for created, text delta, function call, argument delta, and terminal events. OpenAI SDK event objects never cross the provider boundary.

## Streaming retry rule

A stream may retry or fall back only before any event has been emitted to the caller. Once output is visible, a retry could duplicate text or tool arguments, so VeriDeploy surfaces the failure instead. Budget settlement is conservative for a partially delivered stream.

## Cancellation

The provider exposes the Responses cancel operation. Cancellation of an in-flight stream is best-effort when a provider response ID has already been observed. The gateway also exposes explicit cancellation for stored/background responses.

## Persistence

The gateway can persist normalized response snapshots through `ResponsePersistence`. Responses API Adapter includes:

- tenant-scoped in-memory persistence for deterministic tests;
- SQLAlchemy-backed durable persistence for runtime use;
- private tenant-scoped response retrieval.

Later database milestones consolidate this table into the canonical production schema/migrations.

## Error mapping

The OpenAI AI Gateway taxonomy remains authoritative. OpenAI HTTP/SDK errors are normalized to authentication, permission, invalid request, rate limit, timeout, connection, provider unavailable, or unknown categories. Retry-After is captured when available.

## Official implementation references

The implementation follows the OpenAI Responses API and official `openai-python` SDK patterns current at implementation time, including `responses.create(..., stream=True)` event streaming. OpenAI-specific identifiers and API capabilities remain isolated behind `OpenAIProvider`.
