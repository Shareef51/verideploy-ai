# Visual Evidence Agent Verification

Run the focused suite with:

```bash
pytest -q tests/unit/test_visual_evidence_agent.py
```

Run cumulative verification with:

```bash
pytest -q
python -m compileall -q src services workers scripts
```

The focused gate covers authorization, architecture/dashboard query selection, evidence locators, derived-finding observation links, missing visual evidence, low resolution, missing locators, analysis degradation, cross-tenant provenance, trusted document scope, route authorization, SHA mismatch, and refusal to treat remote-like strings as local indexed image paths.

Live OpenAI calls are intentionally not required for deterministic CI. Image Intelligence Layer provider mapping remains separately contract-tested. Live PostgreSQL integration tests remain guarded by `TEST_POSTGRES_URL`.
