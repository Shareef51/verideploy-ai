# Evidence Graph

## Purpose
Evidence Graph turns immutable Immutable Evidence Model evidence and engineering objects into a tenant-isolated relational graph that supports causal and lineage queries without introducing a separate graph database.

## Data model
`graph_entities` stores typed vertices for pull requests, commits, releases, services, incidents, root causes, evidence records, teams, and environments. An entity can optionally point to an exact immutable `evidence_versions.record_id`; that reference is validated in tenant scope before insertion.

`graph_edges` stores typed directed relationships with confidence and optional `occurred_at`, `valid_from`, and `valid_to` timestamps. Source and target indexes support forward and reverse traversal. A database trigger rejects cross-tenant endpoints.

## Query model
Bounded shortest-path traversal is implemented with a PostgreSQL recursive CTE. The query prevents cycles by tracking the visited node array and enforces a caller-supplied maximum depth from 1–12. The primary Evidence Graph acceptance path is:

`pull_request -> modifies_service -> service -> experienced_incident -> incident -> caused_by -> root_cause`

## Lineage visualization
The private FastAPI graph snapshot is proxied through NestJS to the Next.js `/evidence-graph` page. The browser never calls private FastAPI directly. The page renders typed graph nodes, confidence-qualified relationships, and temporal metadata.

## Persistence and tenancy
Both graph tables force PostgreSQL RLS using `app.tenant_id`. The edge-tenant trigger independently verifies that source and target entities belong to the same tenant as the edge, providing a defense in depth against privileged or buggy writes.
