from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from verideploy.postmortems.schemas import (
    Citation, CreatePostmortemCommand, PostmortemRecord, PostmortemStatus, ReviewPostmortemCommand, TimelineEntry,
)


class PostmortemRepository(ABC):
    @abstractmethod
    def create_or_get(self, command: CreatePostmortemCommand, source_version: int) -> tuple[PostmortemRecord, bool]: ...
    @abstractmethod
    def get(self, tenant_id: UUID, postmortem_id: UUID) -> PostmortemRecord | None: ...
    @abstractmethod
    def list(self, tenant_id: UUID, limit: int = 50) -> list[PostmortemRecord]: ...
    @abstractmethod
    def review(self, command: ReviewPostmortemCommand) -> PostmortemRecord: ...


class Base(DeclarativeBase):
    """Declarative base for Postmortem Sequence postmortem persistence."""


class PostmortemRow(Base):
    __tablename__ = "postmortems"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_postmortem_tenant_idempotency_p5"),)
    postmortem_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    investigation_id: Mapped[str] = mapped_column(String(36), index=True)
    requested_by: Mapped[str] = mapped_column(String(36))
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(250))
    status: Mapped[str] = mapped_column(String(40), index=True)
    source_investigation_version: Mapped[int] = mapped_column(Integer)
    evidence_reviewed_by: Mapped[str] = mapped_column(String(36))
    evidence_reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_ids_json: Mapped[str] = mapped_column(Text)
    timeline_json: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str] = mapped_column(Text)
    root_cause_category: Mapped[str] = mapped_column(String(120))
    confidence: Mapped[float] = mapped_column(Float)
    contributing_factors_json: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text)
    remediation_actions_json: Mapped[str] = mapped_column(Text)
    prevention_actions_json: Mapped[str] = mapped_column(Text)
    limitations_json: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[str] = mapped_column(Text)
    approval_reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approval_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _to_record(row: PostmortemRow) -> PostmortemRecord:
    return PostmortemRecord(
        postmortem_id=UUID(row.postmortem_id), tenant_id=UUID(row.tenant_id), investigation_id=UUID(row.investigation_id),
        requested_by=UUID(row.requested_by), correlation_id=UUID(row.correlation_id), idempotency_key=row.idempotency_key,
        title=row.title, status=PostmortemStatus(row.status), source_investigation_version=row.source_investigation_version,
        evidence_reviewed_by=UUID(row.evidence_reviewed_by), evidence_reviewed_at=_aware(row.evidence_reviewed_at),
        evidence_ids=json.loads(row.evidence_ids_json), timeline=[TimelineEntry.model_validate(v) for v in json.loads(row.timeline_json)],
        root_cause=row.root_cause, root_cause_category=row.root_cause_category, confidence=row.confidence,
        contributing_factors=json.loads(row.contributing_factors_json), impact=row.impact,
        remediation_actions=json.loads(row.remediation_actions_json), prevention_actions=json.loads(row.prevention_actions_json),
        limitations=json.loads(row.limitations_json), citations=[Citation.model_validate(v) for v in json.loads(row.citations_json)],
        approval_reviewed_by=UUID(row.approval_reviewed_by) if row.approval_reviewed_by else None,
        approval_reviewed_at=_aware(row.approval_reviewed_at), approval_notes=row.approval_notes,
        created_at=_aware(row.created_at), updated_at=_aware(row.updated_at), version=row.version,
    )


class SqlAlchemyPostmortemRepository(PostmortemRepository):
    def __init__(self, database_url: str, *, create_schema: bool = False) -> None:
        self._engine = create_engine(database_url, future=True)
        if create_schema:
            Base.metadata.create_all(self._engine)
        self._lock = RLock()

    def create_or_get(self, command: CreatePostmortemCommand, source_version: int) -> tuple[PostmortemRecord, bool]:
        with self._lock, Session(self._engine) as session:
            existing = session.scalar(select(PostmortemRow).where(PostmortemRow.tenant_id == str(command.tenant_id), PostmortemRow.idempotency_key == command.idempotency_key))
            if existing:
                return _to_record(existing), False
            now = datetime.now(UTC); b = command.reviewed_evidence
            row = PostmortemRow(
                postmortem_id=str(command.postmortem_id), tenant_id=str(command.tenant_id), investigation_id=str(command.investigation_id),
                requested_by=str(command.requested_by), correlation_id=str(command.correlation_id), idempotency_key=command.idempotency_key,
                title=command.title, status=PostmortemStatus.PENDING_APPROVAL.value, source_investigation_version=source_version,
                evidence_reviewed_by=str(b.reviewed_by), evidence_reviewed_at=b.reviewed_at,
                evidence_ids_json=json.dumps(b.evidence_ids), timeline_json=json.dumps([v.model_dump(mode="json") for v in b.timeline]),
                root_cause=b.root_cause, root_cause_category=b.root_cause_category, confidence=b.confidence,
                contributing_factors_json=json.dumps(b.contributing_factors), impact=b.impact,
                remediation_actions_json=json.dumps(b.remediation_actions), prevention_actions_json=json.dumps(b.prevention_actions),
                limitations_json=json.dumps(b.limitations), citations_json=json.dumps([v.model_dump(mode="json") for v in b.citations]),
                created_at=now, updated_at=now, version=1,
            )
            session.add(row); session.commit(); session.refresh(row)
            return _to_record(row), True

    def get(self, tenant_id: UUID, postmortem_id: UUID) -> PostmortemRecord | None:
        with Session(self._engine) as session:
            row = session.scalar(select(PostmortemRow).where(PostmortemRow.tenant_id == str(tenant_id), PostmortemRow.postmortem_id == str(postmortem_id)))
            return _to_record(row) if row else None

    def list(self, tenant_id: UUID, limit: int = 50) -> list[PostmortemRecord]:
        with Session(self._engine) as session:
            rows = session.scalars(select(PostmortemRow).where(PostmortemRow.tenant_id == str(tenant_id)).order_by(PostmortemRow.created_at.desc()).limit(limit)).all()
            return [_to_record(v) for v in rows]

    def review(self, command: ReviewPostmortemCommand) -> PostmortemRecord:
        with self._lock, Session(self._engine) as session:
            row = session.scalar(select(PostmortemRow).where(PostmortemRow.tenant_id == str(command.tenant_id), PostmortemRow.postmortem_id == str(command.postmortem_id)))
            if row is None:
                raise KeyError(str(command.postmortem_id))
            if row.version != command.expected_version:
                raise ValueError(f"version conflict: expected {command.expected_version}, current {row.version}")
            if row.status == PostmortemStatus.APPROVED.value:
                raise ValueError("approved postmortem is immutable")
            mapping = {"APPROVE": PostmortemStatus.APPROVED, "REQUEST_CHANGES": PostmortemStatus.CHANGES_REQUESTED, "REJECT": PostmortemStatus.REJECTED}
            row.status = mapping[command.decision.value].value
            row.approval_reviewed_by = str(command.reviewer_id); row.approval_reviewed_at = command.reviewed_at; row.approval_notes = command.notes
            row.updated_at = datetime.now(UTC); row.version += 1
            session.commit(); session.refresh(row)
            return _to_record(row)
