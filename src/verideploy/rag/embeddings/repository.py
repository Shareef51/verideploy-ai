from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from verideploy.rag.embeddings.schemas import EmbeddingRecord, EmbeddingState


class EmbeddingRepository(ABC):
    @abstractmethod
    def get_current(self, *, tenant_id: UUID, content_hash: str, model: str, dimensions: int) -> EmbeddingRecord | None: ...

    @abstractmethod
    def save(self, record: EmbeddingRecord) -> EmbeddingRecord: ...

    @abstractmethod
    def mark_stale_for_migration(self, *, tenant_id: UUID, model: str, dimensions: int) -> int: ...

    @abstractmethod
    def transition_state(self, *, tenant_id: UUID, embedding_id: UUID, state: EmbeddingState) -> EmbeddingRecord: ...

    @abstractmethod
    def count_state(self, *, tenant_id: UUID, model: str, dimensions: int, state: EmbeddingState) -> int: ...


class Base(DeclarativeBase):
    pass


class EmbeddingRow(Base):
    __tablename__ = "embedding_cache"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_hash", "model", "dimensions", name="uq_embedding_cache"),
    )
    embedding_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    chunk_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    dimensions: Mapped[int] = mapped_column(Integer)
    registry_version: Mapped[int] = mapped_column(Integer)
    vector_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24), index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _record(row: EmbeddingRow) -> EmbeddingRecord:
    return EmbeddingRecord(
        embedding_id=UUID(row.embedding_id), tenant_id=UUID(row.tenant_id),
        document_id=UUID(row.document_id) if row.document_id else None,
        chunk_id=UUID(row.chunk_id) if row.chunk_id else None,
        content_hash=row.content_hash, model=row.model, dimensions=row.dimensions,
        registry_version=row.registry_version, values=json.loads(row.vector_json),
        state=EmbeddingState(row.state), provider_request_id=row.provider_request_id,
        prompt_tokens=row.prompt_tokens, created_at=_aware(row.created_at), updated_at=_aware(row.updated_at),
    )


class SqlAlchemyEmbeddingRepository(EmbeddingRepository):
    def __init__(self, database_url: str, *, create_schema: bool = False) -> None:
        if database_url.startswith("sqlite") and ":memory:" in database_url:
            self._engine = create_engine(
                database_url, future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
        else:
            self._engine = create_engine(database_url, future=True)
        if create_schema:
            Base.metadata.create_all(self._engine)
        self._lock = RLock()

    def get_current(self, *, tenant_id: UUID, content_hash: str, model: str, dimensions: int) -> EmbeddingRecord | None:
        with Session(self._engine) as session:
            row = session.scalar(select(EmbeddingRow).where(
                EmbeddingRow.tenant_id == str(tenant_id), EmbeddingRow.content_hash == content_hash,
                EmbeddingRow.model == model, EmbeddingRow.dimensions == dimensions, EmbeddingRow.state == EmbeddingState.CURRENT.value,
            ))
            return _record(row) if row else None

    def save(self, record: EmbeddingRecord) -> EmbeddingRecord:
        with self._lock, Session(self._engine) as session:
            existing = session.scalar(select(EmbeddingRow).where(
                EmbeddingRow.tenant_id == str(record.tenant_id), EmbeddingRow.content_hash == record.content_hash,
                EmbeddingRow.model == record.model, EmbeddingRow.dimensions == record.dimensions,
            ))
            if existing:
                return _record(existing)
            row = EmbeddingRow(
                embedding_id=str(record.embedding_id), tenant_id=str(record.tenant_id),
                document_id=str(record.document_id) if record.document_id else None,
                chunk_id=str(record.chunk_id) if record.chunk_id else None,
                content_hash=record.content_hash, model=record.model, dimensions=record.dimensions,
                registry_version=record.registry_version, vector_json=json.dumps(record.values, separators=(",", ":")),
                state=record.state.value, provider_request_id=record.provider_request_id,
                prompt_tokens=record.prompt_tokens, created_at=record.created_at, updated_at=record.updated_at,
            )
            session.add(row); session.commit(); session.refresh(row)
            return _record(row)

    def mark_stale_for_migration(self, *, tenant_id: UUID, model: str, dimensions: int) -> int:
        with self._lock, Session(self._engine) as session:
            result = session.execute(update(EmbeddingRow).where(
                EmbeddingRow.tenant_id == str(tenant_id), EmbeddingRow.model == model,
                EmbeddingRow.dimensions == dimensions, EmbeddingRow.state == EmbeddingState.CURRENT.value,
            ).values(state=EmbeddingState.STALE.value, updated_at=datetime.now(UTC)))
            session.commit()
            return int(result.rowcount or 0)

    def transition_state(self, *, tenant_id: UUID, embedding_id: UUID, state: EmbeddingState) -> EmbeddingRecord:
        with self._lock, Session(self._engine) as session:
            row = session.scalar(select(EmbeddingRow).where(
                EmbeddingRow.tenant_id == str(tenant_id), EmbeddingRow.embedding_id == str(embedding_id)
            ))
            if row is None:
                raise KeyError(str(embedding_id))
            row.state = state.value; row.updated_at = datetime.now(UTC); session.commit(); session.refresh(row)
            return _record(row)

    def count_state(self, *, tenant_id: UUID, model: str, dimensions: int, state: EmbeddingState) -> int:
        with Session(self._engine) as session:
            return len(session.scalars(select(EmbeddingRow).where(
                EmbeddingRow.tenant_id == str(tenant_id), EmbeddingRow.model == model,
                EmbeddingRow.dimensions == dimensions, EmbeddingRow.state == state.value,
            )).all())
