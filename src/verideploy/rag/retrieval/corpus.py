from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.rag.retrieval.schemas import RetrievalDocumentKind


@dataclass(frozen=True)
class RetrievalDocumentInput:
    document_id: UUID
    tenant_id: UUID
    source_key: str
    title: str
    service: str | None = None
    environment: str | None = None
    document_kind: RetrievalDocumentKind = RetrievalDocumentKind.GENERAL
    severity: str | None = None
    team: str | None = None
    occurred_at: datetime | None = None
    required_permission: str = "retrieval.read"


@dataclass(frozen=True)
class RetrievalChunkInput:
    chunk_id: UUID
    tenant_id: UUID
    document_id: UUID
    ordinal: int
    content: str
    chunk_kind: str = "document"
    hierarchy_path: tuple[str, ...] = ()


class PostgresRetrievalCorpusWriter:
    """Minimal Hybrid Retrieval corpus writer for ingestion without bypassing tenant scope."""

    def __init__(self, db: DatabaseManager) -> None:
        if db.engine.dialect.name != "postgresql":
            raise ValueError("PostgresRetrievalCorpusWriter requires PostgreSQL")
        self.db = db

    def upsert_document(self, item: RetrievalDocumentInput) -> None:
        sql = text(
            """
            INSERT INTO retrieval_documents (document_id, tenant_id, source_key, title, service, environment, document_kind, severity, team, occurred_at, required_permission)
            VALUES (:document_id, :tenant_id, :source_key, :title, :service, :environment, :document_kind, :severity, :team, :occurred_at, :required_permission)
            ON CONFLICT (tenant_id, source_key) DO UPDATE SET
                title=EXCLUDED.title, service=EXCLUDED.service, environment=EXCLUDED.environment, document_kind=EXCLUDED.document_kind, severity=EXCLUDED.severity, team=EXCLUDED.team, occurred_at=EXCLUDED.occurred_at, required_permission=EXCLUDED.required_permission
            """
        )
        with self.db.tenant_session(item.tenant_id) as session:
            session.execute(sql, {
                "document_id": str(item.document_id), "tenant_id": str(item.tenant_id),
                "source_key": item.source_key, "title": item.title, "service": item.service,
                "environment": item.environment, "document_kind": item.document_kind.value,
                "severity": item.severity, "team": item.team, "occurred_at": item.occurred_at, "required_permission": item.required_permission,
            })
            session.commit()

    def upsert_chunk(self, item: RetrievalChunkInput) -> str:
        if item.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        if not item.content.strip():
            raise ValueError("content must not be blank")
        content_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        sql = text(
            """
            INSERT INTO retrieval_chunks (chunk_id, tenant_id, document_id, ordinal, content, content_hash, chunk_kind, hierarchy_path)
            VALUES (:chunk_id, :tenant_id, :document_id, :ordinal, :content, :content_hash, :chunk_kind, CAST(:hierarchy_path AS jsonb))
            ON CONFLICT (tenant_id, document_id, ordinal) DO UPDATE SET
                content=EXCLUDED.content, content_hash=EXCLUDED.content_hash, chunk_kind=EXCLUDED.chunk_kind, hierarchy_path=EXCLUDED.hierarchy_path
            """
        )
        with self.db.tenant_session(item.tenant_id) as session:
            session.execute(sql, {
                "chunk_id": str(item.chunk_id), "tenant_id": str(item.tenant_id),
                "document_id": str(item.document_id), "ordinal": item.ordinal,
                "content": item.content, "content_hash": content_hash,
                "chunk_kind": item.chunk_kind, "hierarchy_path": json.dumps(list(item.hierarchy_path)),
            })
            session.commit()
        return content_hash
