# Dynamic Parallelism

## Goal

Dynamic Parallelism adds planner-driven dynamic fan-out/fan-in to the durable LangGraph runtime while preserving the LangGraph State Reducers state/reducer guarantees. The acceptance requirement is that parallel execution lowers latency for independent work without allowing branch completion order to change final investigation state.

## Execution contract

`DynamicParallelExecutor` accepts a typed planner and a registry of source workers. The planner returns a `ParallelPlan` containing stable task identifiers, source names, node names, payloads, per-task deadlines, requested concurrency, and a minimum-success threshold. Plans are content-addressed with deterministic UUIDv5 identifiers.

Execution is bounded by both `requested_concurrency` and the production `LANGGRAPH_PARALLEL_MAX_CONCURRENCY` ceiling. Task count is bounded separately by `LANGGRAPH_PARALLEL_MAX_TASKS`. Each branch is independently protected by a deadline capped by `LANGGRAPH_PARALLEL_MAX_DEADLINE_SECONDS`.

## Planner-driven fan-out

Planner output is the authoritative set of branch tasks. `plan_to_langgraph_sends()` translates the typed plan into canonically ordered LangGraph `Send` objects for graphs that use LangGraph dynamic routing. The runtime-independent executor uses the same plan contract with `asyncio.Semaphore` and `asyncio.wait_for` so concurrency and deadlines remain explicit and testable.

## Deterministic fan-in

Wall-clock completion order is never used as reducer order. Results are sorted by `(source, task_id)` and only then reduced with the LangGraph State Reducers:

- ordered unique append: completed nodes, evidence IDs, citation IDs, approval IDs, errors, runtime events;
- deterministic deep map merge: node outputs and agent outputs;
- conflicting writes: fail with `StateReducerConflict` instead of last-writer-wins.

Branches are not permitted to write identity/scalar fields such as tenant, run ID, investigation ID, graph version, or status through fan-in. This prevents a parallel source from corrupting graph identity.

## Partial completion

A source timeout or exception is represented as a typed `ParallelTaskResult` with `TIMED_OUT` or `FAILED`. Successful branches are preserved. Failed/timed-out branches contribute explicit error records and no partial state update. `minimum_successes_met` and `partial_completion` allow the caller to decide whether downstream reasoning can continue.

## Live node events

Dynamic Parallelism reuses the durable LangGraph Production Runtime `graph_runtime_events` stream rather than creating a second event store. `RuntimeParallelEventSink` emits:

- `graph.parallel.plan.created`
- `graph.parallel.node.started`
- `graph.parallel.node.completed`
- `graph.parallel.node.timed_out`
- `graph.parallel.node.failed`
- `graph.parallel.fan_in.completed`

The final fan-in event includes the deterministic state-update SHA-256. Per-branch timing is telemetry only and is intentionally excluded from the state hash.

## Configuration

- `LANGGRAPH_PARALLEL_MAX_CONCURRENCY=8`
- `LANGGRAPH_PARALLEL_MAX_TASKS=16`
- `LANGGRAPH_PARALLEL_DEFAULT_DEADLINE_SECONDS=30`
- `LANGGRAPH_PARALLEL_MAX_DEADLINE_SECONDS=120`

`create_dynamic_parallel_executor()` in the production graph factory applies these limits centrally so individual business graphs cannot silently choose unbounded fan-out.

## Persistence decision

No new PostgreSQL table is required in Dynamic Parallelism. Live branch events already persist in the LangGraph Production Runtime event table; canonical state/checkpoint history already persists through the official LangGraph checkpointer plus LangGraph State Reducers state snapshots. Adding another persistence authority would create duplicate workflow truth.

## Acceptance benchmark

Run:

```bash
make dynamic-parallel-validate
```

The benchmark executes the same four independent tasks sequentially and in parallel, requires at least 1.75× measured speedup, checks parallel and sequential final-state hashes match, and runs alternate completion orders to prove deterministic fan-in.
