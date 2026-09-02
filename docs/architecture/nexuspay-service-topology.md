# NexusPay Service Topology

NexusPay Service Topology introduces a deterministic synthetic company topology used by later incident, release, and dataset milestones. The topology is a normalized operational graph rather than frontend-only fixture data.

## Model

The seed contains one NexusPay company, five engineering teams and owners, ten services, twelve directed dependencies, development/staging/production environments, twenty production SLOs, and thirty environment-specific deployment records. Stable UUIDv5 identifiers and a canonical SHA-256 digest make regeneration reproducible.

## Persistence

Alembic revision `0010_milestone28_nexuspay_topology` creates normalized tenant-scoped tables for companies, teams, owners, environments, services, dependencies, SLOs, and deployments. Every topology table has forced PostgreSQL row-level security. The idempotent `PostgresTopologyRepository.persist()` path upserts the deterministic snapshot after ensuring the synthetic tenant exists.

## Validation invariants

`validate_topology()` fails when identifiers/slugs collide, references dangle, dependencies self-reference, a team lacks an owner, production is absent, a service lacks a production SLO/deployment, the application dependency graph cycles, or the seed digest differs from canonical content.

## Product path

The browser reads `GET /api/v1/topology/nexuspay` from NestJS. NestJS calls the private FastAPI `GET /internal/v1/topology/nexuspay` with trusted service and tenant headers. FastAPI reads the persisted topology under tenant RLS. The browser never calls the private Python service directly.
