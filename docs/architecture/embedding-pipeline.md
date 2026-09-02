# Embedding Pipeline

## Purpose

Embedding Pipeline creates the production embedding boundary used by later pgvector and hybrid-retrieval milestones. It intentionally does not create a vector index yet; PostgreSQL pgvector Foundation owns PostgreSQL/pgvector foundations.

## Runtime path

1. A trusted service or embedding worker submits a typed `EmbeddingRequest`.
2. The model registry resolves the configured embedding model and exact dimension.
3. Each input receives a SHA-256 content hash.
4. The repository checks the tenant-scoped cache using tenant + content hash + model + dimensions.
5. Cache misses are split into bounded asynchronous batches.
6. The provider adapter calls the official OpenAI embeddings API, or the deterministic provider in CI/demo mode.
7. Provider vector count and vector dimensions are verified before persistence.
8. Valid vectors are persisted with registry version, provider request ID, usage metadata, source document/chunk IDs, and state.
9. Telemetry records cache hits, provider input count, request IDs, prompt-token usage, model, and dimensions.

## Idempotency and tenancy

The cache uniqueness boundary is `(tenant_id, content_hash, model, dimensions)`. Identical text in different tenants is intentionally not shared. This avoids cross-tenant leakage and makes deletion/retention semantics tractable.

## Dimension safety

The registry is authoritative. If a configured model is registered at 3072 dimensions, a request for 1536 does not silently truncate or create a second incompatible representation. A provider returning an unexpected vector length fails before persistence with `EmbeddingDimensionDriftError`.

## Re-embedding lifecycle

Model/dimension changes require an explicit migration plan. Old vectors transition from `CURRENT` to `STALE`; individual records may then enter `REEMBEDDING` and `FAILED`. Later database/index milestones will execute and monitor bulk re-embedding jobs.

## Provider boundary

`OpenAIEmbeddingProvider` constructs a batch request with model, input, `encoding_format="float"`, and the registered dimensions. SDK retries are not relied on by the pipeline; retry policy is owned by VeriDeploy so attempts remain observable and bounded.

## Demo/CI behavior

`DeterministicEmbeddingProvider` generates stable normalized vectors from the model name and input text. It uses the exact production provider contract and makes no network or paid API calls.
