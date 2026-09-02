# Visual Document Retrieval

## Boundary
Visual Document Retrieval retrieves visually relevant PDF pages. It does not perform Multimodal RAG Fusion multimodal evidence fusion or Image Intelligence Layer image interpretation on every page.

## Production path
1. Authorized PDF bytes reach `VisualIndexWorker` from the Multimodal Sequence object-storage/ingestion transport.
2. `PdfPageRenderer` renders every page to a deterministic PNG, extracts the PDF native text layer (no OCR), and records SHA-256, dimensions, document/page identity, and tenant.
3. `VisualRetrieverAdapter` indexes each rendered page.
 - Primary optional backend: Hugging Face native ColPali late-interaction retrieval.
 - CPU fallback: native-text token hashing plus rendered-page visual statistics. It is explicitly identified as a fallback and never claims VLM equivalence.
4. `visual_page_indexes` stores backend/model/index version and either fallback features or a reference to the multi-vector embedding artifact.
5. `POST /internal/v1/retrieval/visual` searches only the caller tenant and returns ranked page IDs, hashes, and internal image references.

## Why multi-vector embeddings are referenced, not forced into pgvector
ColPali produces page-level multi-vector representations and scores them through late interaction. Visual Document Retrieval therefore stores an embedding artifact reference instead of flattening a page into the PostgreSQL pgvector Foundation single-vector schema. A later scaling milestone may adopt a specialized multi-vector index without changing this contract.

## Safety and tenancy
- PDF signature is validated before rendering.
- Maximum pages and DPI are configurable.
- Page outputs are tenant/document namespaced and content-hashed.
- Database tables have explicit tenant columns, application filtering, and forced PostgreSQL RLS.
- The private visual-search API only trusts gateway, investigation-worker, and multimodal-worker service identities.
- The CPU fallback uses the native PDF text layer; it does not run OCR.

## Evaluation
`make visual-retrieval-benchmark` runs fixed architecture/dashboard page queries and fails unless mean NDCG@4 is at least 0.95. The seed benchmark is a regression gate, not a production performance claim.
