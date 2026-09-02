# ADR-0031 — LangSmith is observability only

## Decision

VeriDeploy integrates LangSmith as an optional external trace/evaluation sink. LLMOps Data Platform's tenant-scoped LLMOps ledger remains the durable operational source of truth.

## Consequences

1. Business methods cannot require a successful LangSmith export.
2. External tracing errors never replace provider/domain errors.
3. Raw secrets and unredacted metadata are not exported.
4. Projects/datasets are separated by environment.
5. Dataset export requires a dedicated feature flag and explicit invocation.
6. Correlation IDs link external LangSmith traces back to local evidence and audit history.

## Rejected

- Enabling global tracing as an unconditional production dependency.
- Sending raw prompts/tool payloads by default.
- Using LangSmith as the only cost/audit store.
- Sharing one project across development, staging, and production.
