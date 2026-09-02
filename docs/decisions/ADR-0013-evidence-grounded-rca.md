# ADR-0013 — Evidence-grounded RCA over free-form causal prose

## Status
Accepted

## Decision
RCA generation is split into two layers: the model proposes a strict ranked hypothesis structure, and deterministic application code validates references and computes support, contradiction, temporal, causal, and adjusted-confidence measures.

## Rationale
A language model can be useful for proposing causal explanations but must not be trusted to establish evidence closure or confidence by assertion. This design makes unsupported causes structurally rejectable, keeps trigger/root-cause semantics explicit, and preserves disconfirming evidence for later critic and human-review milestones.

## Consequences
- RCA cannot cite evidence outside the supplied tenant-scoped evidence set.
- Root-cause determination is conservative and may return `false` even when the model proposed a root cause.
- Recommended tests are not executed in this milestone.
- Critic Agent can critique a typed, evidence-linked RCA rather than parsing prose.
