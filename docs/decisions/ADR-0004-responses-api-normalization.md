# ADR-0004 — Normalize the OpenAI Responses API at the provider boundary

- **Status:** Accepted
- **Date:** 2026-08-16

## Context

The OpenAI Responses API supports richer input items, tools, streaming events, provider response IDs, usage details, and cancellation. Allowing these SDK types to flow into agents, graphs, or domain services would tightly couple VeriDeploy to one provider and make streaming/non-streaming behavior inconsistent.

## Decision

`OpenAIProvider` is the only layer that understands OpenAI Responses SDK objects. It converts requests from `AIRequest` and converts provider outputs into `AIResult` / `AIStreamEvent`. The terminal event of a stream contains the same typed `AIResult` contract returned by non-streaming execution.

Streams are never automatically retried after output has become visible. Normalized response snapshots are persisted behind a tenant-scoped persistence interface.

## Consequences

- Provider changes remain localized.
- Agents can use one contract for streaming and non-streaming execution.
- Tool calls have stable internal representations.
- Replay/debugging can use persisted normalized responses.
- Some provider-only features require an explicit contract extension rather than leaking SDK objects into application code.
