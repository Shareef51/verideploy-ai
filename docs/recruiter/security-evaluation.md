# Security and Evaluation

## Security model
- OIDC/PKCE identity at the public boundary.
- RBAC/ABAC and tenant isolation enforced across API, service, repository, retrieval, cache, database, and tool layers.
- Private Python AI endpoints are not browser-facing.
- MCP tools are registered, risk-classified, tenant-guarded, audited, timeout/circuit-breaker protected, and write-disabled by default.
- Consequential actions require dry-run plus human approval.
- Input/retrieval/tool-output/operational guardrails treat retrieved content as untrusted data, not instructions.
- Audit records use append-only tenant-scoped integrity chaining.
- Secret references and redaction prevent credentials from reaching client bundles/logs.

## Evaluation model
Evaluation covers retrieval, RAG faithfulness/citations, agent routing/planning/tool use, LLM quality, hallucination/safety, visual/multimodal quality, regression budgets, security, chaos/load, contracts, and production checkpoint suites.

## Release-candidate truthfulness
The Evaluation Release Candidate Checkpoint separates locally executed gates from CI-enforced gates. A missing environment capability is a limitation to report, not a reason to fabricate a pass.
