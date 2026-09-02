# Retrieval Metrics

Retrieval Metrics turns the 500 Case Evaluation Dataset retrieval cases into an auditable retrieval benchmark. It measures each retriever independently and compares fusion against a named baseline.

## Metrics

- Recall@1, Recall@5, Recall@10 against each case's `ground_truth.relevant_source_ids`.
- Mean reciprocal rank (MRR) from the first relevant result.
- NDCG@10 for ranking quality when multiple evidence sources are relevant.
- Metadata-filter correctness across every returned hit, including tenant and authorization constraints.
- Mean, p50, and p95 retrieval latency.
- Dense, BM25, and fused comparison deltas against the dense baseline.
- Repeated-run mean, sample variance, standard deviation, and 95% confidence interval for quality metrics.

## Deterministic benchmark

`PYTHONPATH=src python scripts/benchmark_retrieval_metrics.py --repeats 5`

The repository benchmark is deliberately synthetic and paid-call-free. It validates metric implementation, reporting, regression gates, and statistical aggregation without depending on an external vector database. Production retrieval adapters can emit the same `RetrievalObservation` contract and reuse the exact metrics/reporting code.

## Gate

The deterministic CI benchmark requires every retriever to satisfy Recall@5 >= 0.90, NDCG@10 >= 0.85, metadata-filter correctness >= 0.99, and requires fused Recall@5 to be at least as strong as dense retrieval. The report is written to `evals/reports/retrieval-metrics.json`.
