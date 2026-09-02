# Complete RAG and Operational Database Schema

Complete RAG Operational Schema closes the relational schema surface required by VeriDeploy AI. It does not duplicate mature Hybrid Retrieval, Visual Document Retrieval, and Supervisor Planner Agent Contracts storage: retrieval documents/chunks, visual pages/indexes, and agent runs remain canonical. A schema catalog maps all required concepts to their authoritative tables.

New Complete RAG Operational Schema tables cover releases, pull requests, commits, incidents, investigations, checkpoints, human reviews, tools, models, evaluations, feedback, jobs, transactional outbox/inbox, and append-only audit events. Every new table is tenant-scoped with forced PostgreSQL RLS.

Lifecycle-bearing records use both application transition validation and PostgreSQL `BEFORE UPDATE OF status` triggers. Cross-tenant operational foreign-key links are rejected by database triggers. Outbox and inbox use tenant-scoped idempotency uniqueness. Audit events are append-only.
