# Synthetic PostgreSQL Operations Guide

The VeriDeploy reference datastore uses PostgreSQL with pgvector. Tenant-owned operational and retrieval tables apply explicit tenant filters and PostgreSQL row-level security. Production transactions set app.tenant_id before tenant-scoped reads and writes.

For checkout-api incident analysis, distinguish database resource saturation from application connection-pool saturation. High application wait time with moderate database CPU can indicate insufficient client-pool capacity or a connection leak. A database restart should not be inferred as the required action without evidence.

Backup and restore procedures use PostgreSQL-native tooling. Schema changes are delivered through Alembic migrations with reversible downgrade paths where supported by the milestone contract.
