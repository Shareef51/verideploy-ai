# RAG Metrics

RAG Metrics adds a production evaluation layer for retrieval-augmented generation without changing business decisions or requiring paid model calls in CI.

## Deterministic metrics

- **Context precision** — fraction of supplied contexts annotated relevant to the case.
- **Context recall** — fraction of required evidence sources present in the supplied context set.
- **Answer relevance** — deterministic token-overlap F1 against the reference answer (or question when no reference answer exists).
- **Faithfulness** — fraction of answer claims backed by at least one supplied supporting source.
- **Citation correctness** — fraction of emitted citations that point to a supplied source explicitly supporting the claim.
- **Citation completeness** — fraction of citation-required claims carrying at least one correct supporting citation.

The structured claim/source contract intentionally separates faithfulness, correctness, and completeness instead of asking one opaque judge for a single score.

## Optional model judge

Model judging is **disabled by default**. When explicitly enabled, the caller must provide a judge implementation. Every result records the judge name, model role, prompt ID, semantic prompt version, and SHA-256 of the exact prompt text. The judge is evaluation-only and cannot change application decisions.

`calibrate_model_judge` compares judge scores with deterministic/labeled calibration examples and reports mean absolute error, bias, Pearson correlation, thresholds, and pass/fail status. Prompt changes therefore produce a new hash/version and require recalibration.

## CI gate

`PYTHONPATH=src python scripts/benchmark_rag_metrics.py`

The benchmark evaluates all 500 synthetic 500 Case Evaluation Dataset cases, writes `evals/reports/rag-metrics.json`, enforces deterministic quality thresholds, and validates the bundled judge calibration fixture without making an external model call.
