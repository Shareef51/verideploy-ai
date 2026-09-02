# Dynamic Parallelism Verification

## Required checks

1. `PYTHONPATH=src:. pytest -q tests/unit/test_dynamic_parallelism.py`
2. `make dynamic-parallel-validate`
3. Run LangGraph Production Runtime, Supervisor Planner Agent Contracts, and LangGraph State Reducers regression tests.
4. Run cumulative Python tests.
5. Verify configuration limits are present in `Settings` and `.env.example`.
6. Verify runtime events use the existing LangGraph Production Runtime event repository.
7. Verify source/credential hygiene and package integrity.

## Acceptance criteria

- planner produces a stable typed plan;
- duplicate task IDs fail validation;
- effective concurrency never exceeds configured maximum;
- per-source deadline returns a typed timeout result;
- source failure does not discard successful branches;
- fan-in result is independent of completion order;
- conflicting branch state writes fail instead of using last-writer-wins;
- live start/completion/timeout/failure/fan-in events are emitted;
- same workload in parallel is measurably faster than sequential execution;
- parallel and sequential final state hashes match;
- alternate completion orders produce the same state hash.

## Environment limitations

The repository declares `langgraph>=0.6,<2`, but the current execution container does not have the LangGraph package installed. The direct `Send` adapter test therefore skips. Core executor/reducer/event/latency behavior is executable without that package. Docker and provisioned PostgreSQL are not required for this milestone because Dynamic Parallelism reuses the existing LangGraph Production Runtime event store and LangGraph State Reducers checkpoint/state persistence contracts.
