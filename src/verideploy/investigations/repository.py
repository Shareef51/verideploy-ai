from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from verideploy.investigations.schemas import (
    CreateInvestigationCommand,
    InvestigationEvent,
    InvestigationRecord,
    InvestigationStatus,
    WorkflowType,
)


class InvestigationRepository(ABC):
    @abstractmethod
    def create_or_get(self, command: CreateInvestigationCommand) -> tuple[InvestigationRecord, bool]: ...

    @abstractmethod
    def get(self, tenant_id: UUID, investigation_id: UUID) -> InvestigationRecord | None: ...

    @abstractmethod
    def list(self, tenant_id: UUID, *, limit: int = 50) -> list[InvestigationRecord]: ...

    @abstractmethod
    def transition(self, tenant_id: UUID, investigation_id: UUID, status: InvestigationStatus, *, error_code: str | None = None, error_message: str | None = None) -> InvestigationRecord: ...

    @abstractmethod
    def request_cancel(self, tenant_id: UUID, investigation_id: UUID, reason: str) -> InvestigationRecord: ...

    @abstractmethod
    def transition_with_event(self, tenant_id: UUID, investigation_id: UUID, status: InvestigationStatus, *, event_type: str, payload: dict[str, object], producer: str = "investigation-worker", error_code: str | None = None, error_message: str | None = None, cancel_reason: str | None = None) -> tuple[InvestigationRecord, InvestigationEvent]: ...

    @abstractmethod
    def append_event(self, event: InvestigationEvent) -> InvestigationEvent: ...

    @abstractmethod
    def list_events(self, tenant_id: UUID, investigation_id: UUID, *, after_sequence: int = 0, limit: int = 200) -> list[InvestigationEvent]: ...


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


class InvestigationRow(Base):
    __tablename__ = "investigation_records"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_investigation_tenant_idempotency_p3"),)

    investigation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    requested_by: Mapped[str] = mapped_column(String(36))
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    query: Mapped[str] = mapped_column(Text)
    workflow_type: Mapped[str] = mapped_column(String(64))
    incident_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_sequence_number: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class InvestigationEventRow(Base):
    __tablename__ = "investigation_events"
    __table_args__ = (
        UniqueConstraint("investigation_id", "sequence_number", name="uq_investigation_sequence_p3"),
        UniqueConstraint("event_id", name="uq_investigation_event_id_p3"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    investigation_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    schema_version: Mapped[str] = mapped_column(String(16))
    sequence_number: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    producer: Mapped[str] = mapped_column(String(100))
    trace_context_json: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _to_record(row: InvestigationRow) -> InvestigationRecord:
    return InvestigationRecord(
        investigation_id=UUID(row.investigation_id), tenant_id=UUID(row.tenant_id), requested_by=UUID(row.requested_by),
        correlation_id=UUID(row.correlation_id), idempotency_key=row.idempotency_key, query=row.query,
        workflow_type=WorkflowType(row.workflow_type), incident_id=row.incident_id, status=InvestigationStatus(row.status),
        cancel_requested=row.cancel_requested, cancel_reason=row.cancel_reason, last_sequence_number=row.last_sequence_number,
        error_code=row.error_code, error_message=row.error_message, created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at), version=row.version,
    )


def _to_event(row: InvestigationEventRow) -> InvestigationEvent:
    import json
    return InvestigationEvent(
        event_id=UUID(row.event_id), event_type=row.event_type, schema_version=row.schema_version,
        tenant_id=UUID(row.tenant_id), correlation_id=UUID(row.correlation_id), investigation_id=UUID(row.investigation_id),
        sequence_number=row.sequence_number, occurred_at=_aware(row.occurred_at), producer=row.producer,
        trace_context=json.loads(row.trace_context_json), payload=json.loads(row.payload_json),
    )


class SqlAlchemyInvestigationRepository(InvestigationRepository):
    def __init__(self, database_url: str, *, create_schema: bool = False) -> None:
        self._engine = create_engine(database_url, future=True)
        if create_schema:
            Base.metadata.create_all(self._engine)
        self._lock = RLock()

    def create_or_get(self, command: CreateInvestigationCommand) -> tuple[InvestigationRecord, bool]:
        with self._lock, Session(self._engine) as session:
            existing = session.scalar(select(InvestigationRow).where(InvestigationRow.tenant_id == str(command.tenant_id), InvestigationRow.idempotency_key == command.idempotency_key))
            if existing:
                return _to_record(existing), False
            now = datetime.now(UTC)
            row = InvestigationRow(
                investigation_id=str(command.investigation_id), tenant_id=str(command.tenant_id), requested_by=str(command.requested_by),
                correlation_id=str(command.correlation_id), idempotency_key=command.idempotency_key, query=command.query,
                workflow_type=command.workflow_type.value, incident_id=command.incident_id, status=InvestigationStatus.ACCEPTED.value,
                cancel_requested=False, last_sequence_number=0, created_at=now, updated_at=now, version=1,
            )
            session.add(row); session.commit(); session.refresh(row)
            return _to_record(row), True

    def get(self, tenant_id: UUID, investigation_id: UUID) -> InvestigationRecord | None:
        with Session(self._engine) as session:
            row = session.scalar(select(InvestigationRow).where(InvestigationRow.tenant_id == str(tenant_id), InvestigationRow.investigation_id == str(investigation_id)))
            return _to_record(row) if row else None

    def list(self, tenant_id: UUID, *, limit: int = 50) -> list[InvestigationRecord]:
        with Session(self._engine) as session:
            rows = session.scalars(select(InvestigationRow).where(InvestigationRow.tenant_id == str(tenant_id)).order_by(InvestigationRow.created_at.desc()).limit(limit)).all()
            return [_to_record(row) for row in rows]

    def transition(self, tenant_id: UUID, investigation_id: UUID, status: InvestigationStatus, *, error_code: str | None = None, error_message: str | None = None) -> InvestigationRecord:
        with self._lock, Session(self._engine) as session:
            row = session.scalar(select(InvestigationRow).where(InvestigationRow.tenant_id == str(tenant_id), InvestigationRow.investigation_id == str(investigation_id)))
            if row is None:
                raise KeyError(str(investigation_id))
            row.status = status.value; row.error_code = error_code; row.error_message = error_message
            row.updated_at = datetime.now(UTC); row.version += 1
            session.commit(); session.refresh(row)
            return _to_record(row)

    def request_cancel(self, tenant_id: UUID, investigation_id: UUID, reason: str) -> InvestigationRecord:
        with self._lock, Session(self._engine) as session:
            row = session.scalar(select(InvestigationRow).where(InvestigationRow.tenant_id == str(tenant_id), InvestigationRow.investigation_id == str(investigation_id)))
            if row is None:
                raise KeyError(str(investigation_id))
            row.cancel_requested = True; row.cancel_reason = reason; row.status = InvestigationStatus.CANCELLING.value
            row.updated_at = datetime.now(UTC); row.version += 1
            session.commit(); session.refresh(row)
            return _to_record(row)


    def transition_with_event(self, tenant_id: UUID, investigation_id: UUID, status: InvestigationStatus, *, event_type: str, payload: dict[str, object], producer: str = "investigation-worker", error_code: str | None = None, error_message: str | None = None, cancel_reason: str | None = None) -> tuple[InvestigationRecord, InvestigationEvent]:
        import json
        with self._lock, Session(self._engine) as session:
            investigation = session.scalar(select(InvestigationRow).where(InvestigationRow.tenant_id == str(tenant_id), InvestigationRow.investigation_id == str(investigation_id)))
            if investigation is None:
                raise KeyError(str(investigation_id))
            now = datetime.now(UTC)
            investigation.status = status.value; investigation.error_code = error_code; investigation.error_message = error_message
            if cancel_reason is not None:
                investigation.cancel_requested = True; investigation.cancel_reason = cancel_reason
            investigation.version += 1; investigation.last_sequence_number += 1; investigation.updated_at = now
            event = InvestigationEvent(
                event_type=event_type, tenant_id=tenant_id, correlation_id=UUID(investigation.correlation_id), investigation_id=investigation_id,
                sequence_number=investigation.last_sequence_number, occurred_at=now, producer=producer, payload=payload,
            )
            event_row = InvestigationEventRow(
                event_id=str(event.event_id), tenant_id=str(event.tenant_id), correlation_id=str(event.correlation_id),
                investigation_id=str(event.investigation_id), event_type=event.event_type, schema_version=event.schema_version,
                sequence_number=event.sequence_number, occurred_at=event.occurred_at, producer=event.producer,
                trace_context_json=json.dumps(event.trace_context, separators=(",", ":"), sort_keys=True),
                payload_json=json.dumps(event.payload, separators=(",", ":"), sort_keys=True),
            )
            session.add(event_row); session.commit(); session.refresh(investigation); session.refresh(event_row)
            return _to_record(investigation), _to_event(event_row)

    def append_event(self, event: InvestigationEvent) -> InvestigationEvent:
        import json
        with self._lock, Session(self._engine) as session:
            investigation = session.scalar(select(InvestigationRow).where(InvestigationRow.tenant_id == str(event.tenant_id), InvestigationRow.investigation_id == str(event.investigation_id)))
            if investigation is None:
                raise KeyError(str(event.investigation_id))
            expected = investigation.last_sequence_number + 1
            if event.sequence_number != expected:
                raise ValueError(f"sequence mismatch: expected {expected}, got {event.sequence_number}")
            row = InvestigationEventRow(
                event_id=str(event.event_id), tenant_id=str(event.tenant_id), correlation_id=str(event.correlation_id),
                investigation_id=str(event.investigation_id), event_type=event.event_type, schema_version=event.schema_version,
                sequence_number=event.sequence_number, occurred_at=event.occurred_at, producer=event.producer,
                trace_context_json=json.dumps(event.trace_context, separators=(",", ":"), sort_keys=True),
                payload_json=json.dumps(event.payload, separators=(",", ":"), sort_keys=True),
            )
            session.add(row); investigation.last_sequence_number = event.sequence_number; investigation.updated_at = event.occurred_at
            session.commit(); session.refresh(row)
            return _to_event(row)

    def list_events(self, tenant_id: UUID, investigation_id: UUID, *, after_sequence: int = 0, limit: int = 200) -> list[InvestigationEvent]:
        with Session(self._engine) as session:
            rows = session.scalars(select(InvestigationEventRow).where(
                InvestigationEventRow.tenant_id == str(tenant_id), InvestigationEventRow.investigation_id == str(investigation_id),
                InvestigationEventRow.sequence_number > after_sequence,
            ).order_by(InvestigationEventRow.sequence_number.asc()).limit(limit)).all()
            return [_to_event(row) for row in rows]
