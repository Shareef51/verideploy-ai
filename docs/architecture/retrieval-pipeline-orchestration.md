# Retrieval Pipeline Orchestration

The Retrieval Pipeline Orchestration retrieval pipeline composes deterministic query normalization/expansion, the canonical Hybrid Retrieval retriever, cross-query fusion, transparent reranking, threshold filtering, source diversification, canonical parent-context resolution, and token-bounded context assembly. Every stage emits a versioned RankingDecision persisted under a tenant-scoped immutable run.

The rerank formula is `0.72 * min(1, fused_score * 60) + 0.28 * lexical_overlap`. Both components and weights are persisted so final ordering can be reconstructed. Parent context is resolved from retrieval_chunks and versioned from canonical content hashes. The browser does not call this private route directly.

Persisted traces are available internally through `GET /internal/v1/retrieval/traces/{run_id}` under trusted-service and tenant scope.
