# LangGraph Production Runtime

## Scope

LangGraph Production Runtime establishes the durable graph runtime only. It does not implement the Supervisor, Planner, RAG, RCA, or Critic agents assigned to later milestones.

## Runtime contract

- `GraphExecutionState` is the typed shared state boundary.
- `GraphRegistry` resolves graph name + semantic version to a graph factory.
- Production graphs compile with LangGraph's PostgreSQL async checkpointer.
- Every run receives a stable `run_id` and `thread_id`; the same thread ID is reused on resume.
- `durability="sync"` is mandatory in this milestone.
- VeriDeploy owns tenant-scoped run metadata and replayable runtime events; LangGraph owns checkpoint/checkpoint-write storage.
- `DeterministicNodeWrapper` adds bounded node execution and an idempotency marker for non-LangGraph recovery paths.
- Graph-level timeout and cancellation are explicit terminal states.

## Persistence split

LangGraph's `AsyncPostgresSaver` owns checkpoint internals. VeriDeploy stores `graph_runs` and `graph_runtime_events` for application status, tenant authorization, replay cursors, auditability, and operations. The two layers intentionally do not duplicate checkpoint payloads.

## Resume semantics

A restarted worker resolves the same graph version and invokes with the existing `thread_id`. LangGraph reloads the latest checkpoint/pending writes. Completed work before a failure is not intentionally re-executed. VeriDeploy's run event indicates whether an invocation is a resume.

## Event streaming

`LangGraphRuntime.stream()` exposes normalized update chunks from LangGraph `astream(..., stream_mode="updates")`. Persisted VeriDeploy runtime events use monotonically increasing per-run sequence numbers for operational replay.

## Non-goals

Human interrupt/resume policy is implemented in Human in the Loop Approval. Agent contracts begin in Supervisor Planner Agent Contracts. Final state reducers/migrations are expanded in LangGraph State Reducers.
