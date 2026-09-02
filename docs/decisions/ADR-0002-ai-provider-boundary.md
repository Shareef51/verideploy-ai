# ADR-0002 — Provider-neutral AI gateway with OpenAI as the production provider

- Status: Accepted
- Milestone: 6

## Context

VeriDeploy is OpenAI-first, but domain code must not depend directly on a provider SDK. Direct SDK calls spread timeout, retry, budget, telemetry, redaction, and error semantics across agents and services and make deterministic testing difficult.

## Decision

All model execution passes through `AIGateway` and the `AIProvider` protocol. `OpenAIProvider` is the production implementation and uses the official asynchronous OpenAI SDK. Unit/default integration tests use `DeterministicTestProvider` and make no network or paid model calls.

The application, not the SDK, owns bounded retry decisions. Provider-specific exceptions are normalized at the adapter edge. Production tenant rate/budget state uses Redis; process-local control is rejected by production settings validation.

## Consequences

- future LangGraph nodes and agents receive one stable AI contract;
- provider request IDs and VeriDeploy request/correlation IDs remain traceable;
- retry behavior is testable and observable;
- model selection remains a separate Model Routing Cost Policy concern;
- Responses API mechanics can evolve inside the adapter without leaking into business logic.
