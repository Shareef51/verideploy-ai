# Hallucination Protection

Hallucination Protection is a claim-release boundary after the Self Corrective RAG self-corrective RAG controller. It verifies proposed claims only against the exact tenant-scoped Self Corrective RAG retrieval context. It does not perform hidden retrieval and does not treat evidence text as executable instructions.

## Flow

1. Load the Self Corrective RAG run under tenant scope.
2. Resolve every proposed evidence `chunk_id` against that stored run.
3. Separate prompt-injection-shaped lines from evidence content.
4. Compute deterministic lexical entailment and contradiction signals.
5. Label each claim `supported`, `uncertain`, or `unsupported`.
6. Cap proposed confidence by evidence entailment and reduce confidence on contradiction.
7. Keep supported claims, qualify uncertain claims, remove unsupported claims.
8. Persist the protected result and claim-level verification history append-only.

## Release invariant

Unsupported material claims are not released. The evaluation metric is the unsupported-material rate in the protected output, while the proposed unsupported rate is retained as adversarial input metadata.

Citation Architecture will add stable citation architecture and deep-linkable locators; Hallucination Protection intentionally uses the already-stored retrieval `chunk_id` references rather than inventing a parallel citation system.
