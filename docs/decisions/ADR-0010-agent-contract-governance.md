# ADR-0010 — Agent contracts are schema-first and authorization-external

**Decision:** Agents return strict Pydantic structured outputs. Authorization and tool budgets are supplied by trusted runtime context and cannot be enlarged by model output. Prompts are file-backed, semantic-versioned, and content-hashed. GitHub operations are read-only in Supervisor Planner Agent Contracts.

**Why:** Model-generated routing is untrusted control data. A route or plan becomes executable only after schema validation, permission intersection, and budget validation. This preserves deterministic governance when these agents are composed inside LangGraph Production Runtime LangGraph graphs.
