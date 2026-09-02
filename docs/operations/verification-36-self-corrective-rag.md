# Self Corrective RAG Verification

Run:

```bash
make self-corrective-rag-validate
PYTHONPATH=src:. pytest -q
```

The PostgreSQL integration test requires `TEST_POSTGRES_URL`. Without it, that test must be reported as skipped rather than passed. External search is disabled by default; verification does not make live external calls.
