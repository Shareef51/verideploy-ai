from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from verideploy.database.base import Base
from verideploy.database.vector_type import Vector

VECTOR_DIMENSIONS = 3072  # immutable migration/index decision, not runtime routing logic


class EmbeddingModel(Base):
    __tablename__ = "embedding_models"
    __table_args__ = (
        UniqueConstraint("model_name", "dimensions", "registry_version", name="uq_embedding_model_version"),
        CheckConstraint("dimensions > 0", name="ck_embedding_models_dimensions_positive"),
    )

    embedding_model_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    registry_version: Mapped[int] = mapped_column(Integer, nullable=False)
    index_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VectorEmbedding(Base):
    __tablename__ = "vector_embeddings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_hash", "embedding_model_id", name="uq_vector_embedding_content"),
        CheckConstraint(f"dimensions = {VECTOR_DIMENSIONS}", name="ck_vector_embeddings_dimensions"),
        Index("ix_vector_embeddings_tenant_model", "tenant_id", "embedding_model_id"),
    )

    embedding_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    embedding_model_id: Mapped[UUID] = mapped_column(ForeignKey("embedding_models.embedding_model_id", ondelete="RESTRICT"), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(nullable=True)
    chunk_id: Mapped[UUID | None] = mapped_column(nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(VECTOR_DIMENSIONS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
