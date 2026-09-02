# ADR-0015 — Manifest-authoritative engineering knowledge corpus

## Decision

Use a checked-in, versioned manifest as the authority for the Engineering Knowledge Base synthetic engineering corpus. Keep source Markdown human-readable, but require cryptographic hashes, deterministic IDs, explicit provenance, labels, retention classes, and synthetic lineage before ingestion.

## Rationale

A loose fixture folder cannot prove which documents were indexed, whether content changed, or whether provenance/retention metadata exists. A manifest provides a deterministic ingestion boundary and enables CI to fail on untracked or modified knowledge.

## Consequences

Content changes require a manifest hash update and corpus-version review. Corpus ingestion reuses the existing retrieval/embedding contracts. Real customer or production documents are outside Engineering Knowledge Base and must enter through authorized ingestion paths with appropriate governance.
