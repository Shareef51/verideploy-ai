from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID
import json

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from verideploy.multimodal.schemas import IngestionCommand, IngestionEvent, IngestionJob, IngestionStatus, Modality


class IngestionRepository(ABC):
    @abstractmethod
    def create_or_get(self, command: IngestionCommand) -> tuple[IngestionJob, bool]: ...
    @abstractmethod
    def get(self, tenant_id: UUID, job_id: UUID) -> IngestionJob | None: ...
    @abstractmethod
    def list_events(self, tenant_id: UUID, job_id: UUID, *, after_sequence: int = 0, limit: int = 200) -> list[IngestionEvent]: ...
    @abstractmethod
    def transition_with_event(self, tenant_id: UUID, job_id: UUID, status: IngestionStatus, *, event_type: str, payload: dict[str, object], error_code: str | None = None, error_message: str | None = None) -> tuple[IngestionJob, IngestionEvent]: ...


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_ingestion_tenant_idempotency_p4"),
        UniqueConstraint("tenant_id", "sha256", "object_key", name="uq_ingestion_object_p4"),
    )
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    requested_by: Mapped[str] = mapped_column(String(36))
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    modality: Mapped[str] = mapped_column(String(24))
    original_filename: Mapped[str] = mapped_column(String(255))
    detected_mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    bucket: Mapped[str] = mapped_column(String(63))
    object_key: Mapped[str] = mapped_column(String(1024))
    object_version: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    last_sequence_number: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class IngestionEventRow(Base):
    __tablename__ = "ingestion_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence_number", name="uq_ingestion_sequence_p4"),
        UniqueConstraint("event_id", name="uq_ingestion_event_id_p4"),
    )
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    schema_version: Mapped[str] = mapped_column(String(16))
    sequence_number: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    producer: Mapped[str] = mapped_column(String(100))
    trace_context_json: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)


def _aware(v: datetime) -> datetime: return v if v.tzinfo else v.replace(tzinfo=UTC)
def _job(r: IngestionJobRow) -> IngestionJob:
    return IngestionJob(job_id=UUID(r.job_id), tenant_id=UUID(r.tenant_id), requested_by=UUID(r.requested_by), correlation_id=UUID(r.correlation_id), idempotency_key=r.idempotency_key, modality=Modality(r.modality), original_filename=r.original_filename, detected_mime_type=r.detected_mime_type, size_bytes=r.size_bytes, sha256=r.sha256, bucket=r.bucket, object_key=r.object_key, object_version=r.object_version, status=IngestionStatus(r.status), last_sequence_number=r.last_sequence_number, error_code=r.error_code, error_message=r.error_message, created_at=_aware(r.created_at), updated_at=_aware(r.updated_at), version=r.version)
def _event(r: IngestionEventRow) -> IngestionEvent:
    return IngestionEvent(event_id=UUID(r.event_id), event_type=r.event_type, schema_version=r.schema_version, tenant_id=UUID(r.tenant_id), correlation_id=UUID(r.correlation_id), job_id=UUID(r.job_id), sequence_number=r.sequence_number, occurred_at=_aware(r.occurred_at), producer=r.producer, trace_context=json.loads(r.trace_context_json), payload=json.loads(r.payload_json))


class SqlAlchemyIngestionRepository(IngestionRepository):
    def __init__(self, database_url: str, *, create_schema: bool=False) -> None:
        self._engine=create_engine(database_url, future=True)
        if create_schema: Base.metadata.create_all(self._engine)
        self._lock=RLock()

    def create_or_get(self, command: IngestionCommand) -> tuple[IngestionJob, bool]:
        with self._lock, Session(self._engine) as s:
            existing=s.scalar(select(IngestionJobRow).where(IngestionJobRow.tenant_id==str(command.tenant_id), IngestionJobRow.idempotency_key==command.idempotency_key))
            if existing: return _job(existing), False
            now=datetime.now(UTC)
            r=IngestionJobRow(job_id=str(command.job_id), tenant_id=str(command.tenant_id), requested_by=str(command.requested_by), correlation_id=str(command.correlation_id), idempotency_key=command.idempotency_key, modality=command.modality.value, original_filename=command.original_filename, detected_mime_type=command.detected_mime_type, size_bytes=command.size_bytes, sha256=command.sha256, bucket=command.bucket, object_key=command.object_key, object_version=command.object_version, status=IngestionStatus.ACCEPTED.value, last_sequence_number=0, created_at=now, updated_at=now, version=1)
            s.add(r); s.commit(); s.refresh(r); return _job(r), True

    def get(self, tenant_id: UUID, job_id: UUID) -> IngestionJob | None:
        with Session(self._engine) as s:
            r=s.scalar(select(IngestionJobRow).where(IngestionJobRow.tenant_id==str(tenant_id), IngestionJobRow.job_id==str(job_id)))
            return _job(r) if r else None

    def list_events(self, tenant_id: UUID, job_id: UUID, *, after_sequence: int=0, limit: int=200) -> list[IngestionEvent]:
        with Session(self._engine) as s:
            rows=s.scalars(select(IngestionEventRow).where(IngestionEventRow.tenant_id==str(tenant_id), IngestionEventRow.job_id==str(job_id), IngestionEventRow.sequence_number>after_sequence).order_by(IngestionEventRow.sequence_number).limit(limit)).all()
            return [_event(r) for r in rows]

    def transition_with_event(self, tenant_id: UUID, job_id: UUID, status: IngestionStatus, *, event_type: str, payload: dict[str, object], error_code: str | None=None, error_message: str | None=None) -> tuple[IngestionJob, IngestionEvent]:
        with self._lock, Session(self._engine) as s:
            r=s.scalar(select(IngestionJobRow).where(IngestionJobRow.tenant_id==str(tenant_id), IngestionJobRow.job_id==str(job_id)))
            if r is None: raise KeyError(str(job_id))
            seq=r.last_sequence_number+1; now=datetime.now(UTC)
            ev=IngestionEvent(event_type=event_type, tenant_id=tenant_id, correlation_id=UUID(r.correlation_id), job_id=job_id, sequence_number=seq, payload=payload)
            r.status=status.value; r.last_sequence_number=seq; r.error_code=error_code; r.error_message=error_message; r.updated_at=now; r.version+=1
            er=IngestionEventRow(event_id=str(ev.event_id), tenant_id=str(tenant_id), correlation_id=r.correlation_id, job_id=str(job_id), event_type=ev.event_type, schema_version=ev.schema_version, sequence_number=seq, occurred_at=ev.occurred_at, producer=ev.producer, trace_context_json=json.dumps(ev.trace_context, separators=(",",":")), payload_json=json.dumps(ev.payload, separators=(",",":"), default=str))
            s.add(er); s.commit(); s.refresh(r); return _job(r), ev
