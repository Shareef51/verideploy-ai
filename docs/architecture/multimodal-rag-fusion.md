# Multimodal RAG Fusion

## Purpose

Multimodal RAG Fusion introduces the deterministic evidence-fusion boundary between retrieval and later reasoning/agent milestones. It does not query external runtime systems and it does not ask an LLM to invent evidence. Hybrid Retrieval supplies text/hybrid retrieval results, Visual Document Retrieval supplies visual page results, and authorized runtime evidence can be supplied through the same strict request contract until the dedicated runtime retrieval layer is implemented in Runtime Evidence Agent.

## Common evidence contract

All selected evidence is normalized into `NormalizedEvidence` with a stable evidence ID, tenant, channel, source identity, content hash, relevance, source confidence, deterministic fusion score, locator, token/image budget cost, and provenance.

Channels are `text`, `visual`, and `runtime`. Visual batches must carry an explicit `visual_tenant_id`; the fusion request rejects missing or cross-tenant visual scope before normalization.

## Fusion score

The Multimodal RAG Fusion score is deterministic and inspectable:

`fusion_score = 0.75 * relevance_score + 0.25 * source_confidence`

The model does not author this numeric score. Text RRF scores and visual scores are normalized inside their own channel before fusion; raw scores from different retrieval systems are not averaged directly.

## Deduplication

Candidates are ordered by fusion score and deduplicated by content hash and stable source identity. The strongest representation is retained. Each selected evidence ID receives exactly one stable `VD-EVID-*` citation.

## Budgeted context assembly

Context selection uses round-robin fairness across available channels so one high-volume channel cannot crowd out all others. The service enforces:

- maximum estimated context tokens;
- maximum image references;
- maximum total evidence items;
- maximum evidence per channel.

Images are represented by safe internal image references; image bytes/Base64 are never counted as text context.

## Grounding contract

`validate_cited_answer` rejects unknown citations and requires every channel that contributed selected context to be cited by the downstream answer. This is a deterministic safety boundary for future agent/RAG answer generation.

## Scope boundary

Multimodal RAG Fusion does not implement Prometheus/log/trace querying, reranking, self-corrective RAG, or final answer generation. Those remain in their dedicated later milestones.
