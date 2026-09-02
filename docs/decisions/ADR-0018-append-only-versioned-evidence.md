# ADR-0018 — Append-only, versioned evidence

## Decision

Persist evidence as immutable version rows plus immutable typed parent links. Do not maintain a mutable canonical evidence payload.

## Rationale

Silent mutation breaks auditability, reproducibility, citation validity, and derivative lineage. New information is represented by a new version with a new hash and record identity. Derived evidence points to the exact parent record versions used to produce it.

## Consequences

Storage grows with revisions, but provenance remains reproducible. Retention metadata is recorded per version; lifecycle deletion is intentionally not implemented in Immutable Evidence Model because it would conflict with the current immutability gate and requires a later policy-controlled archive/tombstone design.
