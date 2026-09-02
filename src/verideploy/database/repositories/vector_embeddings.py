from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text

from verideploy.database.models.embedding import EmbeddingModel, VectorEmbedding
from verideploy.database.session import DatabaseManager


@dataclass(frozen=True)
class VectorNeighbor:
    embedding_id: UUID
    content_hash: str
    distance: float
    document_id: UUID | None
    chunk_id: UUID | None


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".12g") for value in values) + "]"


class PgVectorEmbeddingRepository:
    """Tenant-filtered repository; PostgreSQL RLS is an additional boundary, never the only one."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def get_model(self, *, tenant_id: UUID, model_name: str, dimensions: int) -> EmbeddingModel | None:
        with self.db.tenant_session(tenant_id) as session:
            return session.scalar(
                select(EmbeddingModel).where(
                    EmbeddingModel.model_name == model_name, EmbeddingModel.dimensions == dimensions
                )
            )

    def get_by_id(self, *, tenant_id: UUID, embedding_id: UUID) -> VectorEmbedding | None:
        with self.db.tenant_session(tenant_id) as session:
            return session.scalar(
                select(VectorEmbedding).where(
                    VectorEmbedding.tenant_id == tenant_id, VectorEmbedding.embedding_id == embedding_id
                )
            )

    def nearest(
        self, *, tenant_id: UUID, embedding_model_id: UUID, query_vector: list[float], limit: int = 10
    ) -> list[VectorNeighbor]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if self.db.engine.dialect.name != "postgresql":
            raise RuntimeError("pgvector nearest-neighbor queries require PostgreSQL")
        sql = text(
            """
            SELECT embedding_id, content_hash, document_id, chunk_id,
                   embedding::halfvec(3072) <=> CAST(:query_vector AS halfvec(3072)) AS distance
              FROM vector_embeddings
             WHERE tenant_id = :tenant_id
               AND embedding_model_id = :embedding_model_id
               AND state = 'CURRENT'
             ORDER BY embedding::halfvec(3072) <=> CAST(:query_vector AS halfvec(3072))
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
                },
            ).mappings()
            return [
                VectorNeighbor(
                    embedding_id=UUID(str(row["embedding_id"])),
                    content_hash=str(row["content_hash"]),
                    distance=float(row["distance"]),
                    document_id=UUID(str(row["document_id"])) if row["document_id"] else None,
                    chunk_id=UUID(str(row["chunk_id"])) if row["chunk_id"] else None,
                )
                for row in rows
            ]
