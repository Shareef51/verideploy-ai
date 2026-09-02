# Citation Architecture Verification

Run `make citation-architecture-validate` for deterministic unit coverage. With `TEST_POSTGRES_URL` set, run `pytest -q tests/integration/test_postgres_citation_architecture.py` to verify real migration/RLS/append-only behavior.

Operational checks:

- stable citation ID repeats for identical source/version/hash/locator input;
- page/timecode/code locator validation rejects invalid ranges/paths;
- every released Hallucination Protection claim receives at least one entailing mapping;
- source hash/version mismatch fails citation closure;
- preview requires preview permission plus source permission and current metadata authorization;
- browser deep links never call private FastAPI or expose object-store URLs;
- `0020` upgrades and downgrades cleanly.
