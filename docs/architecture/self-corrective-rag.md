# Self-Corrective RAG

Self Corrective RAG wraps the Retrieval Pipeline Orchestration retrieval pipeline with a bounded corrective controller. It grades retrieved evidence, rewrites queries deterministically, may relax only caller-requested metadata constraints, and stops with an explicit reason. Trusted Metadata Filtering Authorization tenant/permission/service/environment/team/document-kind authorization is immutable throughout retries.

## Controller flow

1. Run authorized Retrieval Pipeline Orchestration retrieval.
2. Grade relevance, source corroboration, and usable context.
3. Stop immediately when evidence is sufficient.
4. Otherwise rewrite the query up to the configured rewrite budget.
5. If permitted and still needed, remove requested metadata constraints while retaining the trusted authorization envelope.
6. Stop when the attempt budget is exhausted or no progress is possible.
7. External search is disabled by default and additionally requires `retrieval.external.read` plus an injected provider.
8. Insufficient evidence returns `answerable=false`, `qualified=true`, and an explicit qualification string.

Run and attempt history is append-only and tenant isolated in PostgreSQL.
