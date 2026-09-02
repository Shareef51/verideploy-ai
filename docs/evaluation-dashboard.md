# Evaluation Dashboard & Experiment Comparison

Evaluation Dashboard turns the Evaluation Framework–58 evaluation stack into an operational LLMOps surface. It does not create new metric definitions; it unifies persisted evaluation runs and the existing retrieval, RAG, agent, LLM-quality, safety, and multimodal metrics.

## Production capabilities

- `EvaluationStore.list_runs()` and `get_case_results()` expose historical persisted runs and their case results.
- `compare_runs()` compares baseline and candidate experiments across aggregate, evaluator, and category dimensions.
- Experiment identity records model, prompt ID/version, and retriever so comparisons are reproducible.
- Release gates block promotion on aggregate regression, per-metric regression, low candidate quality, or excessive failed-case rate.
- `build_case_drilldown()` preserves case/category score, correlation ID, trace ID, span ID, and trace URL.
- `build_trends()` produces chronological historical quality points from completed runs.
- FastAPI exposes private run history, case drill-down, and comparison endpoints.
- NestJS exposes the public BFF under `/api/v1/evaluations/*`; the browser never calls Python directly.
- Next.js adds `/evaluations` to the authenticated production shell with comparison controls, regression bars, category drill-down, release-gate status, trend visualization, case table, and trace links.

## Release gate defaults

| Control | Default |
|---|---:|
| Maximum aggregate drop | 0.01 |
| Maximum individual metric drop | 0.02 |
| Minimum candidate aggregate score | 0.90 |
| Maximum failed-case rate | 0.05 |

A candidate is promotable only when all blocking controls pass. Small non-blocking metric declines are retained as warnings.

## Data integrity

The committed dashboard demo fixtures are explicitly synthetic and exist only to make the recruiter/demo screen useful without external services. Real runtime history and comparisons come from `EvaluationStore` through the private FastAPI service and NestJS boundary. Previous Retrieval Metrics–58 reports remain the authoritative measured benchmark artifacts.
