# RAG Integration and Performance Checkpoint

RAG Integration Performance Checkpoint is a release checkpoint over the existing production RAG implementation. It does not introduce a parallel retriever. It validates the Hybrid Retrieval hybrid keyword/vector fusion, Visual Document Retrieval visual retrieval, Retrieval Pipeline Orchestration, Metadata Filtering Authorization tenant/metadata authorization, Citation Architecture citation closure, and Multi Layer Caching retrieval cache against a deterministic clean-index corpus.

## Protected targets

The release gate protects keyword, dense and hybrid Recall@5, hybrid MRR, visual NDCG@4, metadata-filter correctness, tenant isolation and citation completeness. Clean-index chunking is deterministic, bounded and content-hashed. Cold and warm retrieval latency are measured independently and cache hit ratio is enforced after warm-up.

## Production benchmark

`scripts/validate_rag.py` writes `evals/reports/rag-performance.json`. The deterministic checkpoint is CI-safe. PostgreSQL/pgvector clean-index integration remains covered by the existing `TEST_POSTGRES_URL` integration suite and is intentionally not faked when no PostgreSQL service is present.
