# Long-Running Workflow Durability

Long Running Workflow Durability adds a lease-backed durability control plane around the existing LangGraph Production Runtime LangGraph runtime. It does not replace LangGraph checkpoints, LangGraph State Reducers state snapshots, or Human in the Loop Approval interrupts.

## Authorities

- LangGraph PostgreSQL saver: graph execution checkpoint authority.
- `graph_runs` and `graph_runtime_events`: runtime lifecycle/event authority.
- `graph_state_snapshots`: versioned state/replay audit authority.
- `approval_requests`: high-risk human approval authority.
- Long Running Workflow Durability workflow tables: worker ownership, idempotent step state, recovery and durability event authority.

## Lease ownership

A run has one logical lease keyed by tenant and run. The lease contains an opaque token, owner ID, monotonic version, heartbeat time and expiry. Heartbeats use compare-and-swap on owner/token/version. A worker that loses the lease must stop; an expired lease can be reclaimed by another worker. Cancelled leases cannot be reclaimed.

## Crash recovery

A killed worker stops heartbeating. A recovery scanner selects expired leases only for runs in `RUNNING`, `FAILED` or `TIMED_OUT`; it excludes `WAITING_FOR_APPROVAL`, `CANCELLED` and `COMPLETED`. The replacement worker claims the run and resumes the same `run_id`/`thread_id`, allowing LangGraph to continue from its persisted checkpoint.

## Idempotent steps

External side effects use a stable idempotency key unique within a run. A completed step is terminal and returns its stored output/hash on replay instead of invoking the side effect again. Failed steps may retry with a monotonic attempt number. Timeout/failure state is persisted. Compensation is explicit and runs only after retry exhaustion when configured.

## Operational replay

Durability events are append-only and strictly sequenced per tenant/run. Replay can begin from any sequence and returns a deterministic SHA-256 over canonical event data. Replay is observational; it does not silently execute side effects.
