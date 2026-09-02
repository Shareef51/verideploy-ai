# LangGraph State and Reducers

LangGraph State Reducers finalizes the investigation state compatibility contract around the LangGraph Production Runtime LangGraph runtime. LangGraph's official PostgreSQL checkpointer remains the execution checkpoint authority; VeriDeploy adds version-aware state preparation, deterministic reducer functions, state migration steps, canonical serialization/hashing, a reference-only secret policy, and append-only state snapshots for replay/audit.

## State schema

The current schema is `v3`. Identity fields (`tenant_id`, `investigation_id`, `run_id`, graph/correlation identity) use strict conflict semantics. Parallel collection fields (`completed_nodes`, `evidence_ids`, `citation_ids`, `approval_ids`, errors/events) use a canonical ordered-set reducer. `node_outputs`, `agent_outputs`, `input`, and `final_output` use recursive deterministic map merge; conflicting scalar writes at the same nested path raise `StateReducerConflict` instead of depending on branch completion order.

## Saved-state migrations

Historical LangGraph Production Runtime-style states are treated as schema v1 when no version is present.

- `v1 → v2`: initializes parallel agent/evidence/approval/runtime-event fields.
- `v2 → v3`: initializes citation state and final-output structure.

A state created by a newer runtime version is rejected. This prevents an older worker from silently down-converting a checkpoint.

Before a failed/running investigation resumes, `LangGraphRuntime` reads the current checkpoint. If migration is required and the compiled graph exposes `aupdate_state`, the upgraded state is written to the checkpointer before invocation. A `graph.state.migrated` event records the source/target versions and migration steps.

## Canonical serialization

State is serialized as sorted compact UTF-8 JSON. Timezone-aware datetimes normalize to UTC. The exact canonical document is SHA-256 hashed and stored with every VeriDeploy snapshot along with serializer and encryption-policy versions.

## Encryption policy

Checkpoint state must contain references, not credential material. Passwords, API keys, access/refresh/bearer tokens, authorization headers, private keys, and secret keys are rejected before checkpoint persistence. Secret-manager/object references are allowed. Production PostgreSQL storage/backups remain subject to the platform encryption-at-rest requirements from the database reliability runbooks; LangGraph State Reducers deliberately does not implement custom application cryptography.

## Persistence

Migration `0021_milestone39_langgraph_state_reducers` creates `graph_state_snapshots`. Snapshots are append-only, tenant-RLS protected, run/tenant validated, sequence numbered, schema-versioned, canonical-hashed, and include migration history. The table complements rather than replaces LangGraph's checkpointer tables.
