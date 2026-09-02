# Immutable Evidence Model

Immutable Evidence Model introduces the append-only evidence authority used by later evidence-graph, RCA, critic, postmortem, and audit workflows.

## Design

A logical `evidence_id` may have multiple versions. Every stored version receives its own immutable `record_id`, monotonically increasing version number, canonical content SHA-256, optional object-store reference and object SHA-256, confidence inputs, provenance/source locator, retention policy, and zero or more typed parent links.

Version 1 may be a source record without parents. Any separately derived record must declare at least one parent. Version N+1 must declare the immediately previous version as a `version_of` parent. The PostgreSQL constraint trigger validates this at transaction commit after parent links have been inserted.

## Immutability

`evidence_versions` and `evidence_parent_links` reject SQL UPDATE and DELETE through database triggers. Corrections are represented by a new version rather than mutation. The in-memory deterministic repository deep-copies stored and returned records so test/demo callers cannot mutate persistence by changing a returned nested dictionary.

## Tenant isolation

Both tables enable and force PostgreSQL row-level security using `app.tenant_id`. Parent-link insertion validates that parent, child, and link tenant identities match.

## API

The private FastAPI service exposes create, create-version, record read, latest-version, version history, and immediate lineage endpoints. Only trusted internal service identities may call them, and body/header tenant identity must agree.
