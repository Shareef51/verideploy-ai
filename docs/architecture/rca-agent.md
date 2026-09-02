# RCAAgent

RCA Agent adds an evidence-grounded root-cause-analysis agent on top of the durable LangGraph Production Runtime and the Supervisor Planner Agent Contracts agent governance layer. It consumes already-authorized `NormalizedEvidence` produced by the Multimodal RAG Fusion contract and does not perform retrieval itself.

## Boundaries

- `RCAAgent` requires `rca.analysis.read`.
- The model proposes hypotheses only; VeriDeploy validates evidence references and recomputes evidence-backed confidence.
- Supporting and disconfirming evidence are separate sets and may not overlap.
- Causal links may connect supporting evidence only.
- Trigger, root cause, and alternative are distinct hypothesis kinds.
- Unknown evidence IDs fail the run.
- Cross-tenant evidence and trusted service/environment scope mismatches fail before model execution or acceptance.
- Recommended tests are proposals only. Potentially mutating tests must be marked `requires_approval`; RCA Agent executes no remediation/action.

## Deterministic assessment

For each hypothesis, the runtime calculates:

- support count;
- contradiction count;
- supporting evidence channels;
- temporal-correlation score from evidence timestamps;
- causal-link coverage score;
- evidence-quality score from source confidence and relevance;
- contradiction penalty;
- adjusted confidence capped by the model confidence.

A root cause is not marked determined unless it satisfies configured minimum support and confidence and any required evidence-channel coverage. Disconfirming evidence remains visible and can block determination.

## Persistence

RCA Agent reuses `agent_runs`. Prompt version/hash, input hash, terminal status, and strict output are persisted without adding a redundant RCA-specific table.

## API

`POST /internal/v1/agents/rca` accepts a trusted agent request, permissions, normalized evidence, and optional required evidence channels. Only trusted internal service identities can invoke the route.
