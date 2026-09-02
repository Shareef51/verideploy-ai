from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from verideploy.releases.schemas import ReleaseRiskCommand, ReleaseRiskRecord, ReleaseRiskStatus


class ReleaseRiskRepository(ABC):
    @abstractmethod
    def create_or_get(self, command: ReleaseRiskCommand) -> tuple[ReleaseRiskRecord, bool]: ...

    @abstractmethod
    def get(self, tenant_id: UUID, assessment_id: UUID) -> ReleaseRiskRecord | None: ...

    @abstractmethod
    def list_recent(self, tenant_id: UUID, limit: int = 50) -> list[ReleaseRiskRecord]: ...

    @abstractmethod
    def list_recent(self, tenant_id: UUID, limit: int = 50) -> list[ReleaseRiskRecord]:
        with Session(self._engine) as session:
            rows = session.scalars(select(ReleaseRiskRow).where(ReleaseRiskRow.tenant_id == str(tenant_id)).order_by(ReleaseRiskRow.updated_at.desc(), ReleaseRiskRow.created_at.desc()).limit(max(1, min(limit, 100)))).all()
            return [_to_record(row) for row in rows]

    def transition(self, tenant_id: UUID, assessment_id: UUID, status: ReleaseRiskStatus, *, result_json: str | None = None, error_code: str | None = None, error_message: str | None = None) -> ReleaseRiskRecord: ...


class Base(DeclarativeBase):
    __allow_unmapped__ = True


class ReleaseRiskRow(Base):
    __tablename__ = "release_risk_assessments"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_release_risk_tenant_idempotency"),)

    assessment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    requested_by: Mapped[str] = mapped_column(String(36))
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    repository: Mapped[str] = mapped_column(String(200))
    release_id: Mapped[str] = mapped_column(String(120), index=True)
    commit_sha: Mapped[str] = mapped_column(String(64))
    target_environment: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    policy_input_json: Mapped[str] = mapped_column(Text)
    changed_files_json: Mapped[str] = mapped_column(Text, default="[]")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


def _to_record(row: ReleaseRiskRow) -> ReleaseRiskRecord:
    from verideploy.releases.schemas import ChangedFileInput, ReleaseRiskAssessment, ReleaseRiskPolicyInput

    return ReleaseRiskRecord(
        assessment_id=UUID(row.assessment_id),
        tenant_id=UUID(row.tenant_id),
        requested_by=UUID(row.requested_by),
        correlation_id=UUID(row.correlation_id),
        idempotency_key=row.idempotency_key,
        repository=row.repository,
        release_id=row.release_id,
        commit_sha=row.commit_sha,
        target_environment=row.target_environment,
        status=ReleaseRiskStatus(row.status),
        policy_input=ReleaseRiskPolicyInput.model_validate_json(row.policy_input_json),
        changed_file_details=[ChangedFileInput.model_validate(item) for item in __import__("json").loads(row.changed_files_json or "[]")],
        result=ReleaseRiskAssessment.model_validate_json(row.result_json) if row.result_json else None,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC),
        updated_at=row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=UTC),
        version=row.version,
    )


class SqlAlchemyReleaseRiskRepository(ReleaseRiskRepository):
    def __init__(self, database_url: str, *, create_schema: bool = False) -> None:
        self._engine = create_engine(database_url, future=True)
        if create_schema:
            Base.metadata.create_all(self._engine)
        self._lock = RLock()

    def create_or_get(self, command: ReleaseRiskCommand) -> tuple[ReleaseRiskRecord, bool]:
        with self._lock, Session(self._engine) as session:
            existing = session.scalar(select(ReleaseRiskRow).where(ReleaseRiskRow.tenant_id == str(command.tenant_id), ReleaseRiskRow.idempotency_key == command.idempotency_key))
            if existing:
                return _to_record(existing), False
            now = datetime.now(UTC)
            row = ReleaseRiskRow(
                assessment_id=str(command.assessment_id), tenant_id=str(command.tenant_id), requested_by=str(command.requested_by), correlation_id=str(command.correlation_id), idempotency_key=command.idempotency_key, repository=command.repository, release_id=command.release_id, commit_sha=command.commit_sha, target_environment=command.target_environment, status=ReleaseRiskStatus.ACCEPTED.value, policy_input_json=command.policy.model_dump_json(), changed_files_json=__import__("json").dumps([item.model_dump(mode="json") for item in command.changed_file_details], separators=(",",":")), created_at=now, updated_at=now, version=1,
            )
            session.add(row); session.commit(); session.refresh(row)
            return _to_record(row), True

    def get(self, tenant_id: UUID, assessment_id: UUID) -> ReleaseRiskRecord | None:
        with Session(self._engine) as session:
            row = session.scalar(select(ReleaseRiskRow).where(ReleaseRiskRow.tenant_id == str(tenant_id), ReleaseRiskRow.assessment_id == str(assessment_id)))
            return _to_record(row) if row else None

    def list_recent(self, tenant_id: UUID, limit: int = 50) -> list[ReleaseRiskRecord]:
        with Session(self._engine) as session:
            rows = session.scalars(select(ReleaseRiskRow).where(ReleaseRiskRow.tenant_id == str(tenant_id)).order_by(ReleaseRiskRow.updated_at.desc(), ReleaseRiskRow.created_at.desc()).limit(max(1, min(limit, 100)))).all()
            return [_to_record(row) for row in rows]

    def transition(self, tenant_id: UUID, assessment_id: UUID, status: ReleaseRiskStatus, *, result_json: str | None = None, error_code: str | None = None, error_message: str | None = None) -> ReleaseRiskRecord:
        with self._lock, Session(self._engine) as session:
            row = session.scalar(select(ReleaseRiskRow).where(ReleaseRiskRow.tenant_id == str(tenant_id), ReleaseRiskRow.assessment_id == str(assessment_id)))
            if row is None:
                raise KeyError(str(assessment_id))
            row.status = status.value; row.result_json = result_json; row.error_code = error_code; row.error_message = error_message; row.updated_at = datetime.now(UTC); row.version += 1
            session.commit(); session.refresh(row)
            return _to_record(row)
