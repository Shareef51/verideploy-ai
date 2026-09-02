# Hybrid Retrieval

## Scope

Hybrid Retrieval implements a production retrieval layer that combines PostgreSQL full-text search and pgvector cosine retrieval. It intentionally does not implement visual retrieval, query expansion, reranking, self-corrective retrieval, or parent-child resolution; those belong to later milestones.

## Retrieval channels

### Keyword channel

`retrieval_chunks.search_vector` is a stored PostgreSQL `tsvector`, indexed by GIN. Queries use `websearch_to_tsquery('english', ...)` and `ts_rank_cd` for ranking. Every query includes an explicit `tenant_id` predicate and runs inside the transaction-scoped tenant RLS context.

### Dense channel

The query is embedded through the Embedding Pipeline `EmbeddingPipeline`. Dense candidates are retrieved from the PostgreSQL pgvector Foundation `vector_embeddings` table using cosine distance (`<=>`) and the HNSW cosine index. The query is constrained by tenant, active embedding model, dimensions, and `CURRENT` state.

## Fusion

Raw lexical scores and vector distances are not directly averaged because they have different scales and meanings. Each channel is independently normalized for traceability, while the authoritative fusion score is Reciprocal Rank Fusion:

`rrf_score(d) = Σ 1 / (k + rank_channel(d))`

Hybrid Retrieval uses `k=60` by default. A source-diversity cap prevents one source from occupying the entire result window.

## Traceability

Every hybrid hit contains its channel rank, raw score, normalized score, and RRF contribution. `RetrievalTrace` records candidate counts, selected chunk IDs, fusion constants, and the exact ranking breakdown.

## Migration boundary

Migration `0002_milestone13_hybrid_retrieval` adds the minimal retrieval corpus tables and GIN index required by this milestone. It deliberately avoids the complete document/RAG schema that is scheduled for Complete RAG Operational Schema.
