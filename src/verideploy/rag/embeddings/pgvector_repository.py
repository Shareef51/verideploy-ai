from __future__ import annotations

from datetime import UTC, datetime
import json
from uuid import UUID

from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.rag.embeddings.repository import EmbeddingRepository
from verideploy.rag.embeddings.schemas import EmbeddingRecord, EmbeddingState


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".12g") for value in values) + "]"


def _record(row: dict[str, object]) -> EmbeddingRecord:
    return EmbeddingRecord(
        embedding_id=UUID(str(row["embedding_id"])),
        tenant_id=UUID(str(row["tenant_id"])),
        document_id=UUID(str(row["document_id"])) if row.get("document_id") else None,
        chunk_id=UUID(str(row["chunk_id"])) if row.get("chunk_id") else None,
        content_hash=str(row["content_hash"]),
        model=str(row["model_name"]),
        dimensions=int(row["dimensions"]),
        registry_version=int(row["registry_version"]),
        values=json.loads(str(row["embedding_text"])),
        state=EmbeddingState(str(row["state"])),
        provider_request_id=str(row["provider_request_id"]) if row.get("provider_request_id") else None,
        prompt_tokens=int(row["prompt_tokens"]) if row.get("prompt_tokens") is not None else None,
        created_at=row["created_at"] if isinstance(row["created_at"], datetime) else datetime.now(UTC),
        updated_at=row["updated_at"] if isinstance(row["updated_at"], datetime) else datetime.now(UTC),
    )


class PgVectorEmbeddingCacheRepository(EmbeddingRepository):
    """Embedding Pipeline cache contract implemented on the canonical PostgreSQL pgvector table."""

    def __init__(self, db: DatabaseManager, *, model_name: str, dimensions: int) -> None:
        if db.engine.dialect.name != "postgresql":
            raise ValueError("PgVectorEmbeddingCacheRepository requires PostgreSQL")
        self.db = db
        self.model_name = model_name
        self.dimensions = dimensions

    def _base_select(self) -> str:
        return """
            SELECT ve.embedding_id, ve.tenant_id, ve.document_id, ve.chunk_id, ve.content_hash,
                   em.model_name, ve.dimensions, em.registry_version, ve.embedding::text AS embedding_text, ve.state,
                   ve.provider_request_id, ve.prompt_tokens,
                   ve.created_at, ve.updated_at
              FROM vector_embeddings ve
              JOIN embedding_models em ON em.embedding_model_id = ve.embedding_model_id
        """

    def get_current(self, *, tenant_id: UUID, content_hash: str, model: str, dimensions: int) -> EmbeddingRecord | None:
        if model != self.model_name or dimensions != self.dimensions:
            return None
        sql = text(self._base_select() + """
             WHERE ve.tenant_id=:tenant_id AND ve.content_hash=:content_hash
               AND em.model_name=:model AND ve.dimensions=:dimensions AND ve.state='CURRENT'
             LIMIT 1
        """)
        with self.db.tenant_session(tenant_id) as session:
            row = session.execute(sql, {"tenant_id": str(tenant_id), "content_hash": content_hash, "model": model, "dimensions": dimensions}).mappings().first()
            return _record(dict(row)) if row else None

    def save(self, record: EmbeddingRecord) -> EmbeddingRecord:
        if record.model != self.model_name or record.dimensions != self.dimensions:
            raise ValueError("embedding record does not match active vector index")
        insert = text(f"""
            INSERT INTO vector_embeddings (
                embedding_id, tenant_id, embedding_model_id, document_id, chunk_id, content_hash,
                dimensions, state, provider_request_id, prompt_tokens, embedding, created_at, updated_at
            )
            SELECT :embedding_id, :tenant_id, em.embedding_model_id, :document_id, :chunk_id, :content_hash,
                   :dimensions, :state, :provider_request_id, :prompt_tokens, CAST(:embedding AS vector({self.dimensions})), :created_at, :updated_at
              FROM embedding_models em
             WHERE em.model_name=:model AND em.dimensions=:dimensions AND em.registry_version=:registry_version
            ON CONFLICT (tenant_id, content_hash, embedding_model_id) DO NOTHING
        """)
        with self.db.tenant_session(record.tenant_id) as session:
            result = session.execute(insert, {
                "embedding_id": str(record.embedding_id), "tenant_id": str(record.tenant_id),
                "document_id": str(record.document_id) if record.document_id else None,
                "chunk_id": str(record.chunk_id) if record.chunk_id else None,
                "content_hash": record.content_hash, "dimensions": record.dimensions,
                "state": record.state.value, "provider_request_id": record.provider_request_id,
                "prompt_tokens": record.prompt_tokens, "embedding": _vector_literal(record.values),
                "created_at": record.created_at, "updated_at": record.updated_at,
                "model": record.model, "registry_version": record.registry_version,
            })
            session.commit()
            if result.rowcount == 0:
                existing = self.get_current(
                    tenant_id=record.tenant_id, content_hash=record.content_hash, model=record.model, dimensions=record.dimensions
                )
                if existing is not None:
                    return existing
                raise RuntimeError("embedding model registry row is missing or conflicting vector state exists")
        saved = self.get_current(
            tenant_id=record.tenant_id, content_hash=record.content_hash, model=record.model, dimensions=record.dimensions
        )
        if saved is None:
            raise RuntimeError("saved vector could not be reloaded")
        return saved

    def mark_stale_for_migration(self, *, tenant_id: UUID, model: str, dimensions: int) -> int:
        sql = text("""
            UPDATE vector_embeddings ve SET state='STALE', updated_at=now()
              FROM embedding_models em
             WHERE ve.embedding_model_id=em.embedding_model_id AND ve.tenant_id=:tenant_id
               AND em.model_name=:model AND ve.dimensions=:dimensions AND ve.state='CURRENT'
        """)
        with self.db.tenant_session(tenant_id) as session:
            result = session.execute(sql, {"tenant_id": str(tenant_id), "model": model, "dimensions": dimensions})
            session.commit()
            return int(result.rowcount or 0)

    def transition_state(self, *, tenant_id: UUID, embedding_id: UUID, state: EmbeddingState) -> EmbeddingRecord:
        with self.db.tenant_session(tenant_id) as session:
            result = session.execute(text("UPDATE vector_embeddings SET state=:state, updated_at=now() WHERE tenant_id=:tenant_id AND embedding_id=:embedding_id"), {"state": state.value, "tenant_id": str(tenant_id), "embedding_id": str(embedding_id)})
            session.commit()
            if result.rowcount != 1:
                raise KeyError(str(embedding_id))
            row = session.execute(text(self._base_select() + " WHERE ve.tenant_id=:tenant_id AND ve.embedding_id=:embedding_id"), {"tenant_id": str(tenant_id), "embedding_id": str(embedding_id)}).mappings().one()
            return _record(dict(row))

    def count_state(self, *, tenant_id: UUID, model: str, dimensions: int, state: EmbeddingState) -> int:
        sql = text("""
            SELECT count(*) FROM vector_embeddings ve JOIN embedding_models em ON em.embedding_model_id=ve.embedding_model_id
             WHERE ve.tenant_id=:tenant_id AND em.model_name=:model AND ve.dimensions=:dimensions AND ve.state=:state
        """)
        with self.db.tenant_session(tenant_id) as session:
            return int(session.scalar(sql, {"tenant_id": str(tenant_id), "model": model, "dimensions": dimensions, "state": state.value}) or 0)
