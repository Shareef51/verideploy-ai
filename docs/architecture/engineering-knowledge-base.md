# Engineering Knowledge Base

Engineering Knowledge Base provides a deterministic, synthetic engineering knowledge corpus that feeds the existing VeriDeploy retrieval and embedding stack. The corpus is not an ad-hoc fixture directory: `data/knowledge/manifest.json` is the authority for document identity, category, labels, retrieval kind, tenant, service/environment scope, content hash, provenance URI, retention class, and synthetic lineage.

## Required coverage

The corpus contains one curated document for each required category: architecture, runbook, postmortem, deployment, security, database, Kubernetes, and service. All records are explicitly synthetic and are unsuitable as claims about a real company or production environment.

## Ingestion path

`EngineeringKnowledgeCorpus` validates and loads the file-backed manifest. Deterministic chunk IDs are UUIDv5 values over document ID, ordinal, and chunk content SHA-256. `KnowledgeCorpusIngestor` then reuses `PostgresRetrievalCorpusWriter` for document/chunk upserts and can pass the same chunks to the Embedding Pipeline `EmbeddingPipeline`. No dedicated vector store or retrieval path exists for this corpus alone.

## Lineage and provenance

Every manifest entry includes `source_system`, `source_record_id`, generator name/version, synthetic=true, a unique `synthetic://verideploy/knowledge/...` provenance URI, and SHA-256 of the exact Markdown bytes. Changing content without regenerating the manifest fails validation.

## Retention

`data/knowledge/retention-policy.json` defines three explicit classes: operating, audit, and historical. Validation requires every retention class to have exactly one policy rule and every corpus document to reference a covered class.

## Validation gate

`make knowledge-corpus-validate` fails if any required category is missing, a file is missing/untracked, a content hash differs, provenance/lineage is invalid, category labels are absent, or retention coverage is incomplete. The validator writes `artifacts/corpus-validation.json` for reproducibility.
