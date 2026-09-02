# Retrieval Pipeline Orchestration Verification

Run `pytest -q tests/unit/test_retrieval_pipeline_orchestration.py` and then the cumulative suite. Validate Alembic upgrade/downgrade for revision 0016, OpenAPI route presence, Python compileall, contract parsing, TypeScript syntax, and source/credential scans. Provisioned PostgreSQL execution is only claimed when TEST_POSTGRES_URL is available.
