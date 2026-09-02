# Supervisor, Planner, and Agent Contracts

Supervisor Planner Agent Contracts adds typed, versioned agent contracts on top of the LangGraph Production Runtime LangGraph runtime. It does not create a second orchestration loop. Supervisor, planner, and GitHub agents are designed to become deterministic graph nodes/subgraphs while LangGraph Production Runtime continues to own checkpoints, resume, cancellation, and streaming.

## Boundaries

- `SupervisorAgent` emits a strict `SupervisorDecision` and may route only to `planning` or `github` in this milestone.
- `PlanningAgent` emits a validated ordered DAG with at most 12 steps and an aggregate tool-call budget.
- `GitHubAgent` is read-only. It may plan and execute only repository/PR/commit/workflow reads through an injected `GitHubToolPort`.
- Authorization is caller supplied; agents can request permissions but cannot grant them.
- Every prompt is immutable by semantic version and SHA-256.
- Every run persists prompt hash, input hash, status, output, and tool budget consumption.
- External GitHub writes remain disabled; later integration milestones may bind a real GitHub/MCP adapter to the read-only port.

## Reproducibility

Reproduction keys are `agent_name + prompt_name/version/hash + input_sha256`. Schema validation rejects unknown fields and invalid routes/plans before persistence as completed output.
