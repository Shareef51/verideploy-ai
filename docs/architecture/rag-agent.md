# RAGAgent

## Purpose

RAG Agent introduces a schema-first RAGAgent on top of the Hybrid Retrieval engine and Supervisor Planner Agent Contracts agent contracts. The agent analyzes a retrieval objective, selects exactly one authorized retrieval mode, applies trusted metadata scope, optionally expands the query within a bounded tool budget, merges duplicate chunks, and returns evidence plus a deterministic sufficiency decision. It does not generate a final factual answer.

## Execution path

1. A trusted internal caller supplies `AgentRequest`, identity headers, and `rag.retrieval.read`.
2. `RAGAgent` invokes the Structured Output Platform structured-output path with prompt `rag@1.0.0`.
3. `RAGQueryAnalysis` validates intent, retrieval mode, document kinds, filters, expansion count, and `top_k`.
4. Trusted request `service`/`environment` scope is authoritative. Model output may not broaden it, and omitted filters inherit trusted scope.
5. Each primary/expanded query consumes one `ToolBudget` call before retrieval.
6. `HybridRetrieverRAGTool` delegates to the Hybrid Retrieval retriever in keyword, dense, or hybrid mode. Keyword mode does not call the embedding pipeline; dense mode does not call PostgreSQL FTS.
7. Results are tenant-checked, deduplicated by `chunk_id`, and ranked deterministically by fused score/source/chunk identity.
8. Stable `RAGEvidenceItem` identifiers are generated from tenant + chunk identity.
9. `EvidenceSufficiency` is computed deterministically from evidence count, source diversity, and required document-kind coverage.
10. The complete result, prompt hash, input hash, and tool usage are persisted through the Supervisor Planner Agent Contracts agent-run repository.

## Retrieval document kinds

RAG Agent adds explicit retrieval metadata:

- `historical_incident`
- `runbook`
- `architecture`
- `general`

Alembic revision `0008_milestone20_rag_agent` adds `retrieval_documents.document_kind`, an allowed-value check, and a tenant/kind index. Hybrid Retrieval keyword and dense queries accept the same kind filter, so the RAGAgent never needs a bypass repository.

## Retrieval modes

- `keyword`: PostgreSQL full-text search only; no embedding call.
- `dense`: query embedding + pgvector only; no full-text query.
- `hybrid`: both channels with existing Hybrid Retrieval RRF/source-diversity logic.

The model chooses from this closed enum. It cannot name arbitrary vector stores, search APIs, or SQL.

## Query expansion

The schema permits at most three unique, nonblank expansion queries. The primary query and each expansion consume one retrieval tool call. The whole set is rejected before retrieval when it exceeds the supplied budget, preventing partial execution of an already-invalid plan.

## Evidence sufficiency

Sufficiency is not another model call. It is an auditable deterministic result with reason codes:

- `insufficient_evidence_count`
- `insufficient_source_diversity`
- `required_document_kind_missing`
- `sufficient`

This makes insufficient evidence a first-class state for RAG Agent and a safe input for later answering/critic milestones.

## Boundaries

RAG Agent does not implement visual-evidence reasoning (Visual Evidence Agent), runtime-source querying (Runtime Evidence Agent), final multimodal answer generation, or a new vector store. It reuses the production retrieval, embedding, pgvector, tenant, structured-output, prompt-versioning, and agent-run persistence boundaries already built in prior milestones.
