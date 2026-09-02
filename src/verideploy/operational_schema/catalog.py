from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SchemaBinding:
    concept: str
    table: str
    schema_generation: int
    tenant_scoped: bool = True


REQUIRED_SCHEMA_CONCEPTS = (
    "releases", "pull_requests", "commits", "incidents", "documents", "pages", "chunks",
    "visual_indexes", "investigations", "checkpoints", "reviews", "agent_runs", "tools", "models",
    "evaluations", "feedback", "jobs", "outbox", "inbox", "audit",
)

OPERATIONAL_SCHEMA_CATALOG = {
    "releases": SchemaBinding("releases", "releases", 32),
    "pull_requests": SchemaBinding("pull_requests", "pull_requests", 32),
    "commits": SchemaBinding("commits", "commits", 32),
    "incidents": SchemaBinding("incidents", "incidents", 32),
    "documents": SchemaBinding("documents", "retrieval_documents", 13),
    "pages": SchemaBinding("pages", "visual_pages", 14),
    "chunks": SchemaBinding("chunks", "retrieval_chunks", 13),
    "visual_indexes": SchemaBinding("visual_indexes", "visual_page_indexes", 14),
    "investigations": SchemaBinding("investigations", "investigations", 32),
    "checkpoints": SchemaBinding("checkpoints", "investigation_checkpoints", 32),
    "reviews": SchemaBinding("reviews", "human_reviews", 32),
    "agent_runs": SchemaBinding("agent_runs", "agent_runs", 19),
    "tools": SchemaBinding("tools", "tool_registry", 32),
    "models": SchemaBinding("models", "model_registry", 32),
    "evaluations": SchemaBinding("evaluations", "evaluations", 32),
    "feedback": SchemaBinding("feedback", "feedback", 32),
    "jobs": SchemaBinding("jobs", "jobs", 32),
    "outbox": SchemaBinding("outbox", "outbox", 32),
    "inbox": SchemaBinding("inbox", "inbox", 32),
    "audit": SchemaBinding("audit", "audit_events", 32),
}


def validate_schema_catalog() -> dict[str, object]:
    missing = sorted(set(REQUIRED_SCHEMA_CONCEPTS) - set(OPERATIONAL_SCHEMA_CATALOG))
    duplicate_tables: list[str] = []
    seen: set[str] = set()
    for binding in OPERATIONAL_SCHEMA_CATALOG.values():
        if binding.table in seen:
            duplicate_tables.append(binding.table)
        seen.add(binding.table)
        if not binding.tenant_scoped:
            raise ValueError(f"operational schema concept must be tenant scoped: {binding.concept}")
    if missing:
        raise ValueError(f"missing schema concepts: {', '.join(missing)}")
    # Reuse of a historical canonical table is intentional; duplicate concept bindings are not.
    if duplicate_tables:
        raise ValueError(f"duplicate schema table bindings: {', '.join(sorted(set(duplicate_tables)))}")
    return {
        "valid": True,
        "concept_count": len(REQUIRED_SCHEMA_CONCEPTS),
        "tables": sorted(b.table for b in OPERATIONAL_SCHEMA_CATALOG.values() if b.schema_generation == 32),
        "reused_tables": sorted(b.table for b in OPERATIONAL_SCHEMA_CATALOG.values() if b.schema_generation < 32),
    }
