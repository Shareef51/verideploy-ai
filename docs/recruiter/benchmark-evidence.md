# Measured Engineering Evidence

This page lists values already produced by repository test/evaluation artifacts. It does not convert estimates or CI-only gates into measured local facts.

| Area | Measured evidence | Source |
|---|---:|---|
| Cumulative regression | 700 passed / 0 failed | `evals/reports/release-candidate-benchmarks.json` |
| Python coverage | 87.32% | same benchmark report |
| Critical mutation probes | 4/4 killed | same benchmark report |
| Security critical findings | 0 | same benchmark report |
| Final contract families | 9 | final response/event schema contract evidence |
| Hybrid Recall@5 | 1.0 | `evals/reports/rag-performance.json` |
| Hybrid MRR | 1.0 | same RAG performance report |
| Agentic orchestration aggregate path score | 1.0 | `evals/reports/agentic-orchestration.json` |
| Multimodal integration clean traceability | 1.0 | `evals/reports/multimodal-integration.json` |
| Production operations critical gaps | 0 | `evals/reports/production-operations.json` |
| Production architecture nodes | 15 | `evals/reports/final-production-architecture.json` |
| Production architecture data-flow edges | 19 | same production architecture report |
| AI-engineering evidence-backed skill claims | 14 | `evals/reports/ai-engineering-jd-mapping.json` |

## Benchmark interpretation rules
- Sub-millisecond clean-index RAG latency is an **in-process deterministic benchmark**, not production network latency.
- Multimodal Killer Demo latency/cost fields are **configured/estimated synthetic-demo values**, not production billing evidence.
- Browser execution is CI-enforced where local Playwright dependencies were unavailable; unexecuted local browser tests are not reported as local passes.
