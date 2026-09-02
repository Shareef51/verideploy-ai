# Evidence Graph Verification

Run focused deterministic tests:

```bash
PYTHONPATH=src:. pytest -q tests/unit/test_evidence_graph.py
```

Run the cumulative suite:

```bash
PYTHONPATH=src:. pytest -q
```

In a provisioned PostgreSQL environment set `TEST_POSTGRES_URL` to enable `tests/integration/test_postgres_evidence_graph.py`. The integration gate migrates to head, seeds the deterministic NexusPay graph, verifies the PR → service → incident → root-cause recursive path, and checks that another tenant sees no graph entities.

After normal application migrations, seed the production-shaped synthetic graph with:

```bash
make evidence-graph-seed
```

The UI is available at `/evidence-graph` through the normal Next.js → NestJS → private FastAPI boundary.
