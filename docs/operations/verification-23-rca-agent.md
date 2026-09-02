# RCA Agent Verification

RCA Agent verification covers strict RCA schema validation, evidence-reference closure, tenant/scope controls, trigger-versus-root-cause separation, temporal/causal scoring, contradiction penalties, required-channel sufficiency, prompt/routing integration, private API authorization, and the fixed synthetic top-k RCA benchmark.

Run:

```bash
PYTHONPATH=src:. pytest -q tests/unit/test_rca_agent.py
PYTHONPATH=src:. python scripts/benchmark_rca.py
PYTHONPATH=src:. pytest -q
```

The benchmark gate requires Top-3 accuracy >= 0.80 and unsupported-cause rate = 0 on the fixed seeded incident set. The benchmark is a deterministic regression gate, not a production accuracy claim.
