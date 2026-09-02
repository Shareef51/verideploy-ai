# Hallucination Protection Verification

Run:

```bash
make hallucination-protection-validate
PYTHONPATH=src:. pytest -q tests/unit/test_hallucination_protection.py
PYTHONPATH=src:. pytest -q
```

The adversarial evaluator includes unsupported causal claims, fake evidence IDs, contradictory evidence, prompt-injection-shaped evidence, and a partially supported claim. Acceptance requires the released unsupported-material rate to be at or below `HALLUCINATION_UNSUPPORTED_MATERIAL_THRESHOLD`.

The live PostgreSQL integration test additionally verifies tenant isolation and append-only mutation rejection when `TEST_POSTGRES_URL` is configured.
