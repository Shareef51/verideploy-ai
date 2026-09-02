# Automated Evaluation Regression Gates

Automated Evaluation Regression Gates converts VeriDeploy's evaluation platform into an enforceable PR/CI release policy.

## Controls

- PR/CI quality budgets at aggregate and per-metric level.
- Blocking vs warning thresholds with metric floors.
- Paired case-level 95% confidence intervals for statistical regression evidence.
- Historical flaky-case detection by score variance; flaky cases stay visible but are excluded from blocking calculations.
- Model, prompt, and retriever change attribution using run experiment metadata.
- Audited override approvals with approver, reason, ticket, policy ID, candidate run, and optional expiry.
- Explicit baseline promotion by dataset/environment after a releasable non-override gate.
- Release-policy enforcement via non-zero CLI exit status for blocked candidates.

## Safety properties

Overrides never make a blocked run baseline-promotable. Baseline promotion requires an existing persisted run. Expired or mismatched overrides are ignored. Statistical evidence supplements, rather than replaces, fixed quality budgets so tiny statistically significant changes cannot unexpectedly block releases.

## CI

Use `scripts/evaluate_regression_gate.py` with the persistent evaluation SQLite store, baseline run ID, candidate run ID, and report output. A blocked gate exits `2`; `--non-blocking` can be used for informational branches.
