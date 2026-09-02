# ADR-0017 — Deterministic synthetic incident dataset

## Decision

Use a checked-in, content-addressed synthetic incident dataset generated from the deterministic NexusPay topology. Keep labels separate from observable telemetry text, include both causal and non-causal evidence, and persist stable incident IDs under tenant RLS.

## Rationale

The project needs reproducible agent/RCA/evaluation scenarios without using private production data. Deterministic generation makes benchmark regressions explainable, while leakage checks prevent trivial classification through machine-label strings or cross-split duplicate families.
