# RAG Agent Verification

Run in a provisioned environment:

```bash
PYTHONPATH=src:. pytest -q
PYTHONPATH=src:. python -m compileall -q src services workers
PYTHONPATH=src:. alembic upgrade 0008_milestone20_rag_agent --sql
PYTHONPATH=src:. alembic downgrade 0008_milestone20_rag_agent:0007_milestone19_agent_contracts --sql
```

For the live PostgreSQL metadata-filter integration test set `TEST_POSTGRES_URL` to an isolated PostgreSQL 16 + pgvector database. That test migrates to head and proves a runbook-only lexical query excludes an architecture document within the same tenant.

RAG Agent focused checks cover query-analysis schema rules, exact keyword/dense tool selection, no embedding call in keyword mode, no FTS call in dense mode, query-expansion budget enforcement, cross-expansion deduplication, trusted metadata scope, cross-tenant retrieval rejection, deterministic evidence sufficiency, supervisor/planner RAG routing, prompt versioning, private API authorization, and migration metadata.
