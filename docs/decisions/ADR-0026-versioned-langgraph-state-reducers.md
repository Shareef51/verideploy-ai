# ADR-0026 — Versioned LangGraph state with explicit reducers

## Decision

Use an explicit state schema version and registered one-step migrations for durable investigation state. Use field-specific reducers instead of generic dictionary update or list concatenation. Persist VeriDeploy-owned append-only state snapshots alongside, not inside, the official LangGraph checkpointer schema.

## Rationale

Long-running incident investigations may survive application deploys. A checkpoint therefore has an API compatibility surface just like a database record. Generic last-writer-wins merging is unsafe under parallel agent execution because results can depend on completion order. Explicit reducers make merge semantics reviewable and testable, while stepwise migrations allow old active investigations to resume after a release.

## Encryption boundary

State is a control-plane document, not a secret store. Credentials must remain in configured secret providers and state may keep only references. This avoids inventing an application encryption format and keeps checkpoint replay deterministic.

## Consequences

New state fields must define reducer/migration behavior before becoming durable. Removing or changing a field requires a new migration step. Workers must fail closed on future state versions they do not understand.
