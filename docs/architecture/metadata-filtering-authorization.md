# Metadata Filtering and Authorization

Metadata Filtering Authorization makes retrieval scope monotonic across keyword, dense/vector, visual, cache, and source-preview paths. Trusted caller authorization is separate from model/request filters. The effective scope is the intersection of trusted service/environment/team/type constraints and requested constraints; a contradiction is represented as an empty scope and never retried without filters.

The canonical filter dimensions are tenant, service, environment, document type, severity, occurred-at date range, team, and required permission. PostgreSQL keyword/vector/visual/source-preview queries apply those predicates before ranking or preview construction. Tenant RLS remains the final database boundary. Retrieval caches include the effective-scope SHA-256 fingerprint in the key so a broader cached result cannot satisfy a narrower caller.

`retrieval_documents` and `visual_documents` now persist severity, team, occurred_at, and required_permission. Visual documents additionally gain service, environment, and document_kind metadata. Corpus and visual ingestion APIs carry the same metadata fields so filtering is not merely query-time decoration.
