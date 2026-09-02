# LangSmith Integration

## Goal

LangSmith is an opt-in external observability plane. It must never become an execution dependency or replace the authoritative LLMOps Data Platform LLMOps ledger.

## Data flow

`business execution -> local LLMOps persistence -> best-effort LangSmith export`

The model gateway creates a deterministic correlation root and child LLM run. Orchestrated retrieval can create a retriever child under the same root. Correlation IDs and prompt-version metadata are preserved; raw model inputs/outputs are represented by hashes in the default model tracing path.

## Safety invariants

- Disabled by default.
- Staging/production require an API key when enabled.
- Project names are environment-qualified: `<prefix>-<environment>`.
- LangSmith client/transport failures are captured as observer diagnostics and are never raised into business logic.
- Metadata/payloads pass through the LLMOps Data Platform recursive redactor before generic export.
- Dataset export is a separate explicit opt-in capability and is never called automatically by production execution.
- LLMOps Data Platform PostgreSQL LLMOps data remains authoritative for audit, retention, cost, and investigation traceability.

## Run hierarchy

A deterministic UUIDv5 root is derived from tenant + correlation ID. Model/retrieval spans derive stable child IDs from tenant + correlation ID + source record key. This provides cross-referenceable hierarchy without making LangSmith IDs business identifiers.

## Dataset hooks

Dataset names are environment-qualified (`<dataset-prefix>-<environment>-<logical-name>`). Inputs, outputs, and metadata are redacted before export. Dataset hook failure returns `False` and records a diagnostic; it cannot fail an investigation.
