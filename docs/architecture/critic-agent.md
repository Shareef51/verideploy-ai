# CriticAgent

Critic Agent adds the evidence-grounded critic boundary after RCA Agent RCA generation. The critic never creates a new RCA and never executes remediation. It deterministically extracts one claim per typed RCA hypothesis, checks cited evidence for lexical entailment, treats disconfirming evidence as contradiction input, recalibrates confidence, optionally performs bounded read-only Hybrid Retrieval hybrid retrieval, and requires human escalation when a root-cause claim remains unsupported, partial, contradicted, low-confidence, or unresolved.

## Flow

`RCAAgentResult -> deterministic claims -> evidence closure -> entailment/contradiction -> bounded follow-up retrieval -> confidence adjustment -> pass/escalate`

The existing Supervisor Planner Agent Contracts agent-run repository remains the audit store. No new database table is introduced.

## Safety properties

- Critic requires `critic.analysis.read`.
- Tenant, service, and environment scope are checked before criticism or retrieval.
- Follow-up retrieval is read-only and bounded by both `CRITIC_MAX_FOLLOWUPS` and `CRITIC_AGENT_TOOL_BUDGET`.
- Unknown RCA evidence IDs fail closed.
- Supporting and disconfirming evidence remain distinct.
- Hallucinated and contradictory root-cause claims cannot pass.
- A failed critic returns a structured human-escalation decision rather than silently accepting the RCA.
