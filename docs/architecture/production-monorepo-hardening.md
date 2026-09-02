# Production Monorepo Hardening

Production Monorepo Hardening makes repository structure an enforced production contract. The root release version is `0.67.0` across TypeScript workspaces, Python, and Helm. `config/monorepo/policy.json` defines package ownership and generated-contract inputs; `config/monorepo/integrity.json` fingerprints those contracts plus the Turbo/workspace graph.

CI first runs `scripts/validate_monorepo.py`. Incremental routing is provided by `scripts/ci/affected.py`; global policy changes invalidate every group. `.github/CODEOWNERS` maps application, AI-platform, infrastructure, contract, and security areas to owning teams.

Reproducibility rule: dependency resolution is frozen in CI when lockfiles exist. This execution environment cannot reach public package indexes, so Production Monorepo Hardening does not fabricate lockfiles. The repository validator instead fails on version/generated-contract drift and CI is configured to use frozen installs once release lockfiles are materialized by a networked dependency-resolution job.
