# Safety & Hallucination Metrics

Safety Hallucination Metrics adds deterministic, CI-safe adversarial evaluation for hallucination and safety behavior without requiring paid model calls.

## Metrics

- **Unsupported-claim rate** — fraction of emitted claims not present in the grounded support set.
- **Unsafe-action rate** — fraction of proposed actions outside the case's allow-list.
- **Prompt-injection resistance** — verifies adversarial instructions are detected/ignored rather than followed.
- **Authorization-boundary correctness** — verifies required authorization is present and attempted cross-tenant/role access is blocked.
- **Abstention quality** — scores whether the system abstains exactly when grounding/policy requires it and records a reason.
- **Policy-violation detection** — F1 over expected versus detected safety-control violations.
- **Failure-to-trace linkage** — requires correlation ID, trace ID, and span ID for every safety failure.

## Adversarial gate

`PYTHONPATH=src python scripts/benchmark_safety_metrics.py`

The benchmark uses all 500 synthetic 500 Case Evaluation Dataset cases and injects deterministic adversarial conditions. The profile is explicitly synthetic and validates the metric/gating infrastructure rather than claiming real-world safety performance for a vendor model.

CI fails when any configured maximum-rate or minimum-score threshold is violated. The report is written to `evals/reports/safety-hallucination-metrics.json` and retains trace-linkage metadata for every imperfect case.
