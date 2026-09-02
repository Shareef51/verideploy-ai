# ADR-0005 — Visual Evidence Boundary

- Status: Accepted
- Milestone: 9

## Decision

Visual model access is centralized in `ImageIntelligenceService`. Callers provide authorized image bytes plus provenance; the service performs secure preparation, detail selection, typed OpenAI input construction, and strict result validation.

The layer never accepts arbitrary remote URLs. Direct observations and derived inferences are different schema types, and inferences must reference validated observations.

## Rationale

This keeps image security, model semantics, provenance, and hallucination controls out of UI/business code and prepares a stable contract for later visual retrieval and multimodal RAG milestones.

## Consequences

Image bytes are decoded/re-encoded before provider submission, which costs CPU and can change the binary hash while preserving visual content. Both original and prepared hashes are retained. `original` detail is opt-in instead of assumed available for every configured model.
