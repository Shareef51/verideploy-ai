# ADR-0027 — Deterministic, bounded dynamic parallelism

## Status
Accepted.

## Context
The investigation planner needs to fan out to independent evidence sources to reduce wall-clock latency. Naive `asyncio.gather` or unconstrained LangGraph dynamic routing can overload providers, allow a slow source to block the whole investigation, and create completion-order-dependent state when branches write overlapping fields.

## Decision
Use one typed `ParallelPlan` as the fan-out contract and execute it under centrally configured task-count, concurrency, and deadline ceilings. Translate the same plan to LangGraph `Send` objects when native dynamic routing is used. Represent every branch completion, timeout, and failure explicitly.

Fan-in must ignore completion order. Completed results are sorted by `(source, task_id)` and reduced only through the LangGraph State Reducers deterministic reducers. Branches may update only reducer-safe fields. Incompatible writes fail closed.

Partial completion is valid when successful branch results remain useful. It is represented explicitly through result counts, `partial_completion`, and `minimum_successes_met`; no failed branch may inject partial state.

## Consequences
- Independent source work can execute concurrently and reduce latency.
- Provider pressure is bounded by policy rather than planner preference.
- Slow sources have per-source failure domains.
- State output is replayable and independent of scheduler timing.
- Live events are observable while final state remains deterministic.
- Business graphs retain responsibility for deciding whether the minimum successful evidence set is sufficient for downstream reasoning.
