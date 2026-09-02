# ADR-0006 — Pydantic is the authoritative structured-output boundary

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Provider-side JSON Schema constraints substantially reduce malformed model output, but VeriDeploy still requires a provider-independent correctness boundary before data reaches domain services or persistence.

## Decision

1. Register every production structured output as a versioned Pydantic model.
2. Export the model's JSON Schema for provider-side strict structured output.
3. Validate every returned JSON payload again with the registered Pydantic model.
4. Permit only syntax-level local unwrapping; never invent fields or silently coerce semantic types.
5. Retry invalid provider output only within a small explicit budget.
6. Defer successful-response persistence until local validation has passed.
7. Generate TypeScript contracts from the same schema registry.

## Consequences

- Business code never consumes unvalidated model dictionaries.
- Provider changes do not change the domain validation boundary.
- Schema versions are explicit and exportable.
- Invalid output may require another model call, so retry limits remain cost-governed by the existing AI gateway.
