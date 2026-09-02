from __future__ import annotations

import hashlib
from uuid import UUID
from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.rag.orchestration.schemas import ParentResolvedContext


class PostgresParentResolver:
    """Resolve stable parent context from the canonical Hybrid Retrieval corpus."""
    def __init__(self, db: DatabaseManager, *, neighbor_radius: int = 1) -> None:
        self.db = db
        self.neighbor_radius = max(0, min(3, neighbor_radius))

    def resolve(self, *, tenant_id: UUID, chunk_id: UUID, fallback: str, source_key: str, title: str, document_id: UUID) -> ParentResolvedContext:
        sql = text("""
            WITH anchor AS (
                SELECT document_id, ordinal, hierarchy_path FROM retrieval_chunks
                 WHERE tenant_id=:tenant_id AND chunk_id=:chunk_id
            )
            SELECT c.content, c.content_hash, c.ordinal
              FROM retrieval_chunks c JOIN anchor a ON a.document_id=c.document_id
             WHERE c.tenant_id=:tenant_id
               AND (c.hierarchy_path = a.hierarchy_path OR c.ordinal BETWEEN a.ordinal - :radius AND a.ordinal + :radius)
             ORDER BY CASE WHEN c.hierarchy_path = a.hierarchy_path THEN 0 ELSE 1 END, abs(c.ordinal-a.ordinal), c.ordinal
             LIMIT 7
        """)
        with self.db.tenant_session(tenant_id) as session:
            rows = list(session.execute(sql, {"tenant_id": str(tenant_id), "chunk_id": str(chunk_id), "radius": self.neighbor_radius}).mappings())
        content = "\n\n".join(str(r["content"]) for r in rows) if rows else fallback
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        versions = ":".join(str(r["content_hash"]) for r in rows) if rows else digest
        source_version = hashlib.sha256(versions.encode()).hexdigest()
        return ParentResolvedContext(chunk_id=chunk_id, document_id=document_id, source_key=source_key, title=title, content=content, content_sha256=digest, source_version=source_version, estimated_tokens=max(1,(len(content)+3)//4))
