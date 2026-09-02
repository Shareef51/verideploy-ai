# Critic Agent Verification

Run:

```bash
pytest -q tests/unit/test_critic_agent.py
PYTHONPATH=src python scripts/benchmark_critic.py
pytest -q
python -m compileall -q src services workers scripts tests
```

The critic benchmark contains one supported RCA, one deliberately hallucinated RCA, and one deliberately contradictory RCA. The gate passes only when the supported RCA passes and both invalid RCAs fail.

Live PostgreSQL integration tests still require `TEST_POSTGRES_URL`. Critic Agent does not add a database migration because `agent_runs` already provides the durable agent audit boundary.
