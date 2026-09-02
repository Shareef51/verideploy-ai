# ADR-0008 — Deterministic Multimodal Evidence Fusion

- **Status:** Accepted
- **Milestone:** 15

## Decision

Use one provider-neutral `NormalizedEvidence` contract for text, visual, and runtime channels. Normalize scores only within each source channel, calculate a deterministic bounded fusion score, deduplicate before context assembly, and require citation closure for all selected evidence.

## Rationale

Retrieval systems expose incomparable raw scores. Directly averaging RRF values, cosine distances, visual late-interaction scores, and runtime anomaly values would be numerically misleading. A deterministic normalization/fusion layer keeps ranking auditable and prevents an LLM from secretly becoming the authoritative evidence selector.

## Consequences

- Every selected evidence item has one stable citation.
- Context/image budgets are enforced before model invocation.
- Cross-channel coverage can be verified mechanically.
- Runtime retrieval remains replaceable and can be added later without changing the fusion contract.
