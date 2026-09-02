# ADR-0009 — Critic evidence validation boundary

## Decision

Critic Agent extracts claims deterministically from the typed RCA Agent RCA result instead of asking another LLM to paraphrase the RCA. Citation entailment and contradiction checks are deterministic and evidence-bound. A bounded read-only retrieval path may add supporting evidence when a claim is weak, but it may not broaden trusted tenant/service/environment scope.

## Rationale

A model-based critic that first rewrites the RCA can introduce a second hallucination surface. Deterministic claim extraction ensures the critic evaluates exactly what RCA Agent asserted. The lexical entailment gate is intentionally conservative and auditable; later evaluation milestones can calibrate or replace it without changing the agent contract.

## Consequences

- Unsupported and contradictory claims fail closed.
- False negatives are possible with paraphrased evidence; bounded follow-up retrieval reduces that risk.
- Human escalation is explicit whenever automated evidence closure is insufficient.
