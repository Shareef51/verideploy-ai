from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.rag.retrieval.schemas import RetrievalDocumentKind


@dataclass(frozen=True)
class KeywordRow:
    chunk_id: UUID
    document_id: UUID
    source_key: str
    title: str
    content: str
    score: float
    document_kind: RetrievalDocumentKind = RetrievalDocumentKind.GENERAL


@dataclass(frozen=True)
class DenseRow:
    chunk_id: UUID
    document_id: UUID
    source_key: str
    title: str
    content: str
    distance: float
    document_kind: RetrievalDocumentKind = RetrievalDocumentKind.GENERAL


class RetrievalRepository(ABC):
    @abstractmethod
    def keyword_search(
        self,
        *,
        tenant_id: UUID,
        query: str,
        limit: int,
        service: str | None = None,
        environment: str | None = None,
        document_kinds: list[RetrievalDocumentKind] | None = None,
    ) -> list[KeywordRow]: ...

    @abstractmethod
    def dense_search(
        self,
        *,
        tenant_id: UUID,
        embedding_model_id: UUID,
        query_vector: list[float],
        limit: int,
        service: str | None = None,
        environment: str | None = None,
        document_kinds: list[RetrievalDocumentKind] | None = None,
    ) -> list[DenseRow]: ...

    @abstractmethod
    def get_embedding_model_id(self, *, tenant_id: UUID, model_name: str, dimensions: int) -> UUID: ...


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".12g") for value in values) + "]"


class PostgresHybridRetrievalRepository(RetrievalRepository):
    """PostgreSQL FTS + pgvector repository with explicit tenant filtering and RLS context."""
    supports_scope = True

    def __init__(self, db: DatabaseManager) -> None:
        if db.engine.dialect.name != "postgresql":
            raise ValueError("PostgresHybridRetrievalRepository requires PostgreSQL")
        self.db = db

    def get_embedding_model_id(self, *, tenant_id: UUID, model_name: str, dimensions: int) -> UUID:
        sql = text(
            "SELECT embedding_model_id FROM embedding_models "
            "WHERE model_name=:model_name AND dimensions=:dimensions "
            "ORDER BY registry_version DESC LIMIT 1"
        )
        with self.db.tenant_session(tenant_id) as session:
            value = session.scalar(sql, {"model_name": model_name, "dimensions": dimensions})
        if value is None:
            raise KeyError(f"embedding model is not registered: {model_name}/{dimensions}")
        return UUID(str(value))

    def keyword_search(
        self,
        *,
        tenant_id: UUID,
        query: str,
        limit: int,
        service: str | None = None,
        environment: str | None = None,
        document_kinds: list[RetrievalDocumentKind] | None = None,
        effective_scope=None,
    ) -> list[KeywordRow]:
        if not query.strip() or (effective_scope is not None and effective_scope.empty):
            return []
        sql = text(
            """
            WITH q AS (SELECT websearch_to_tsquery('english', :query) AS tsq)
            SELECT c.chunk_id, c.document_id, d.source_key, d.title, d.document_kind, c.content,
                   ts_rank_cd(c.search_vector, q.tsq, 32) AS score
              FROM retrieval_chunks c
              JOIN retrieval_documents d ON d.document_id=c.document_id AND d.tenant_id=c.tenant_id
              CROSS JOIN q
             WHERE c.tenant_id=:tenant_id
               AND c.search_vector @@ q.tsq
               AND (:service IS NULL OR d.service=:service)
               AND (:environment IS NULL OR d.environment=:environment)
               AND (:document_kinds IS NULL OR d.document_kind = ANY(CAST(:document_kinds AS text[])))
               AND (:scope_services IS NULL OR d.service = ANY(CAST(:scope_services AS text[])))
               AND (:scope_envs IS NULL OR d.environment = ANY(CAST(:scope_envs AS text[])))
               AND (:scope_kinds IS NULL OR d.document_kind = ANY(CAST(:scope_kinds AS text[])))
               AND (:scope_sevs IS NULL OR d.severity = ANY(CAST(:scope_sevs AS text[])))
               AND (:scope_teams IS NULL OR d.team = ANY(CAST(:scope_teams AS text[])))
               AND (:from_ts IS NULL OR d.occurred_at >= :from_ts)
               AND (:to_ts IS NULL OR d.occurred_at <= :to_ts)
               AND d.required_permission = ANY(CAST(:permissions AS text[]))
             ORDER BY score DESC, c.chunk_id ASC
             LIMIT :limit
            """
        )
        with self.db.tenant_session(tenant_id) as session:
            rows = session.execute(
                sql,
                {
                    "tenant_id": str(tenant_id),
                    "query": query,
                    "limit": limit,
                    "service": service,
                    "environment": environment,
                    "document_kinds": [item.value for item in document_kinds] if document_kinds else None,
                    "scope_services": list(effective_scope.services) if effective_scope and effective_scope.services is not None else None,
                    "scope_envs": list(effective_scope.environments) if effective_scope and effective_scope.environments is not None else None,
                    "scope_kinds": list(effective_scope.document_kinds) if effective_scope and effective_scope.document_kinds is not None else None,
                    "scope_sevs": list(effective_scope.severities) if effective_scope and effective_scope.severities is not None else None,
                    "scope_teams": list(effective_scope.teams) if effective_scope and effective_scope.teams is not None else None,
                    "from_ts": effective_scope.occurred_from if effective_scope else None, "to_ts": effective_scope.occurred_to if effective_scope else None,
                    "permissions": list(effective_scope.permissions) if effective_scope else ["retrieval.read"],
                },
            ).mappings()
            return [
                KeywordRow(
                    chunk_id=UUID(str(row["chunk_id"])),
                    document_id=UUID(str(row["document_id"])),
                    source_key=str(row["source_key"]),
                    title=str(row["title"]),
                    content=str(row["content"]),
                    score=float(row["score"]),
                    document_kind=RetrievalDocumentKind(str(row["document_kind"])),
                )
                for row in rows
            ]

    def dense_search(
        self,
        *,
        tenant_id: UUID,
        embedding_model_id: UUID,
        query_vector: list[float],
        limit: int,
        service: str | None = None,
        environment: str | None = None,
        document_kinds: list[RetrievalDocumentKind] | None = None,
        effective_scope=None,
    ) -> list[DenseRow]:
        if effective_scope is not None and effective_scope.empty:
            return []
        sql = text(
            """
            SELECT c.chunk_id, c.document_id, d.source_key, d.title, d.document_kind, c.content,
                   ve.embedding::halfvec(3072) <=> CAST(:query_vector AS halfvec(3072)) AS distance
              FROM vector_embeddings ve
              JOIN retrieval_chunks c ON c.chunk_id=ve.chunk_id AND c.tenant_id=ve.tenant_id
              JOIN retrieval_documents d ON d.document_id=c.document_id AND d.tenant_id=c.tenant_id
             WHERE ve.tenant_id=:tenant_id
               AND ve.embedding_model_id=:embedding_model_id
               AND ve.state='CURRENT'
               AND (:service IS NULL OR d.service=:service)
               AND (:environment IS NULL OR d.environment=:environment)
               AND (:document_kinds IS NULL OR d.document_kind = ANY(CAST(:document_kinds AS text[])))
               AND (:scope_services IS NULL OR d.service = ANY(CAST(:scope_services AS text[])))
               AND (:scope_envs IS NULL OR d.environment = ANY(CAST(:scope_envs AS text[])))
               AND (:scope_kinds IS NULL OR d.document_kind = ANY(CAST(:scope_kinds AS text[])))
               AND (:scope_sevs IS NULL OR d.severity = ANY(CAST(:scope_sevs AS text[])))
               AND (:scope_teams IS NULL OR d.team = ANY(CAST(:scope_teams AS text[])))
               AND (:from_ts IS NULL OR d.occurred_at >= :from_ts)
               AND (:to_ts IS NULL OR d.occurred_at <= :to_ts)
               AND d.required_permission = ANY(CAST(:permissions AS text[]))
             ORDER BY ve.embedding::halfvec(3072) <=> CAST(:query_vector AS halfvec(3072)), ve.embedding_id ASC
             LIMIT :limit
            """
        )
        with self.db.tenant_session(tenant_id) as session:
            rows = session.execute(
                sql,
                {
                    "tenant_id": str(tenant_id),
                    "embedding_model_id": str(embedding_model_id),
                    "query_vector": _vector_literal(query_vector),
                    "limit": limit,
                    "service": service,
                    "environment": environment,
                    "document_kinds": [item.value for item in document_kinds] if document_kinds else None,
                    "scope_services": list(effective_scope.services) if effective_scope and effective_scope.services is not None else None,
                    "scope_envs": list(effective_scope.environments) if effective_scope and effective_scope.environments is not None else None,
                    "scope_kinds": list(effective_scope.document_kinds) if effective_scope and effective_scope.document_kinds is not None else None,
                    "scope_sevs": list(effective_scope.severities) if effective_scope and effective_scope.severities is not None else None,
                    "scope_teams": list(effective_scope.teams) if effective_scope and effective_scope.teams is not None else None,
                    "from_ts": effective_scope.occurred_from if effective_scope else None, "to_ts": effective_scope.occurred_to if effective_scope else None,
                    "permissions": list(effective_scope.permissions) if effective_scope else ["retrieval.read"],
                },
            ).mappings()
            return [
                DenseRow(
                    chunk_id=UUID(str(row["chunk_id"])),
                    document_id=UUID(str(row["document_id"])),
                    source_key=str(row["source_key"]),
                    title=str(row["title"]),
                    content=str(row["content"]),
                    distance=float(row["distance"]),
                    document_kind=RetrievalDocumentKind(str(row["document_kind"])),
                )
                for row in rows
            ]
