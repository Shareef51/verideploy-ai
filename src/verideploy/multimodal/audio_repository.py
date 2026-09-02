from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from contextlib import contextmanager
from collections.abc import Iterator
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from verideploy.multimodal.audio_transcription import (
    AudioFormat,
    AudioTranscriptionRecord,
    TranscriptSegment,
    TranscriptionStatus,
)


class Base(DeclarativeBase):
    pass


class TranscriptionRow(Base):
    __tablename__ = "audio_transcriptions"
    transcription_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False, index=True)
    ingestion_job_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    audio_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_mime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    language: Mapped[str | None] = mapped_column(String(20))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "ingestion_job_id", "model", name="uq_audio_transcription_identity"),)


class SegmentRow(Base):
    __tablename__ = "audio_transcript_segments"
    segment_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    transcription_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("audio_transcriptions.transcription_id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "transcription_id", "sequence_number", name="uq_audio_segment_sequence"),
        UniqueConstraint("tenant_id", "evidence_id", name="uq_audio_segment_evidence"),
    )


class SqlAlchemyTranscriptionRepository:
    def __init__(self, database_url: str, *, create_schema: bool = False) -> None:
        kwargs: dict[str, object] = {"future": True}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.engine = create_engine(database_url, **kwargs)
        self._lock = RLock()
        if create_schema:
            Base.metadata.create_all(self.engine)

    @contextmanager
    def _tenant_session(self, tenant_id: UUID) -> Iterator[Session]:
        session = Session(self.engine)
        try:
            with session.begin():
                if self.engine.dialect.name == "postgresql":
                    session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)})
                yield session
        finally:
            session.close()

    def get(self, tenant_id: UUID, transcription_id: UUID) -> AudioTranscriptionRecord | None:
        with self._tenant_session(tenant_id) as session:
            row = session.scalar(select(TranscriptionRow).where(TranscriptionRow.tenant_id == tenant_id, TranscriptionRow.transcription_id == transcription_id))
            return self._to_record(session, row) if row else None

    def create_or_get(self, record: AudioTranscriptionRecord) -> tuple[AudioTranscriptionRecord, bool]:
        with self._lock, self._tenant_session(record.tenant_id) as session:
            row = session.scalar(select(TranscriptionRow).where(TranscriptionRow.tenant_id == record.tenant_id, TranscriptionRow.transcription_id == record.transcription_id))
            if row:
                return self._to_record(session, row), False
            session.add(self._row(record))
        current = self.get(record.tenant_id, record.transcription_id)
        assert current is not None
        return current, True

    def mark_processing(self, tenant_id: UUID, transcription_id: UUID, attempt_count: int) -> None:
        with self._lock, self._tenant_session(tenant_id) as session:
            row = session.scalar(select(TranscriptionRow).where(TranscriptionRow.tenant_id == tenant_id, TranscriptionRow.transcription_id == transcription_id).with_for_update())
            if row is None:
                raise KeyError("transcription not found")
            row.status = TranscriptionStatus.PROCESSING.value
            row.attempt_count = attempt_count
            row.error_code = None
            row.error_message = None
            row.updated_at = datetime.now(UTC)

    def complete(self, record: AudioTranscriptionRecord) -> AudioTranscriptionRecord:
        with self._lock, self._tenant_session(record.tenant_id) as session:
            row = session.scalar(select(TranscriptionRow).where(TranscriptionRow.tenant_id == record.tenant_id, TranscriptionRow.transcription_id == record.transcription_id).with_for_update())
            if row is None:
                raise KeyError("transcription not found")
            row.status = TranscriptionStatus.COMPLETED.value
            row.language = record.language
            row.duration_seconds = record.duration_seconds
            row.provider_request_id = record.provider_request_id
            row.attempt_count = record.attempt_count
            row.error_code = None
            row.error_message = None
            row.updated_at = record.updated_at
            for segment in record.segments:
                existing = session.get(SegmentRow, segment.segment_id)
                if existing is None:
                    session.add(self._segment_row(segment))
                else:
                    # Stable segment ID makes replay/resume idempotent.
                    existing.text = segment.text
                    existing.speaker = segment.speaker
                    existing.raw_text_sha256 = segment.raw_text_sha256
                    existing.evidence_id = segment.evidence_id
                    existing.start_seconds = segment.start_seconds
                    existing.end_seconds = segment.end_seconds
        result = self.get(record.tenant_id, record.transcription_id)
        assert result is not None
        return result

    def fail(self, tenant_id: UUID, transcription_id: UUID, *, attempt_count: int, error_code: str, error_message: str) -> None:
        with self._lock, self._tenant_session(tenant_id) as session:
            row = session.scalar(select(TranscriptionRow).where(TranscriptionRow.tenant_id == tenant_id, TranscriptionRow.transcription_id == transcription_id).with_for_update())
            if row is None:
                raise KeyError("transcription not found")
            row.status = TranscriptionStatus.FAILED.value
            row.attempt_count = attempt_count
            row.error_code = error_code
            row.error_message = error_message[:500]
            row.updated_at = datetime.now(UTC)

    @staticmethod
    def _row(record: AudioTranscriptionRecord) -> TranscriptionRow:
        return TranscriptionRow(
            transcription_id=record.transcription_id, tenant_id=record.tenant_id, ingestion_job_id=record.ingestion_job_id,
            correlation_id=record.correlation_id, model=record.model, audio_sha256=record.audio_sha256,
            detected_mime_type=record.detected_mime_type.value, status=record.status.value, language=record.language,
            duration_seconds=record.duration_seconds, provider_request_id=record.provider_request_id, attempt_count=record.attempt_count,
            error_code=record.error_code, error_message=record.error_message, created_at=record.created_at, updated_at=record.updated_at,
        )

    @staticmethod
    def _segment_row(segment: TranscriptSegment) -> SegmentRow:
        return SegmentRow(
            segment_id=segment.segment_id, transcription_id=segment.transcription_id, tenant_id=segment.tenant_id,
            sequence_number=segment.sequence_number, start_seconds=segment.start_seconds, end_seconds=segment.end_seconds,
            speaker=segment.speaker, text=segment.text, raw_text_sha256=segment.raw_text_sha256, evidence_id=segment.evidence_id,
        )

    @staticmethod
    def _to_record(session: Session, row: TranscriptionRow) -> AudioTranscriptionRecord:
        segment_rows = session.scalars(select(SegmentRow).where(SegmentRow.tenant_id == row.tenant_id, SegmentRow.transcription_id == row.transcription_id).order_by(SegmentRow.sequence_number)).all()
        segments = [
            TranscriptSegment(
                segment_id=seg.segment_id, transcription_id=seg.transcription_id, tenant_id=seg.tenant_id,
                sequence_number=seg.sequence_number, start_seconds=seg.start_seconds, end_seconds=seg.end_seconds,
                speaker=seg.speaker, text=seg.text, raw_text_sha256=seg.raw_text_sha256, evidence_id=seg.evidence_id,
            ) for seg in segment_rows
        ]
        return AudioTranscriptionRecord(
            transcription_id=row.transcription_id, tenant_id=row.tenant_id, ingestion_job_id=row.ingestion_job_id,
            correlation_id=row.correlation_id, model=row.model, audio_sha256=row.audio_sha256,
            detected_mime_type=AudioFormat(row.detected_mime_type), status=TranscriptionStatus(row.status), language=row.language,
            duration_seconds=row.duration_seconds, provider_request_id=row.provider_request_id, attempt_count=row.attempt_count,
            error_code=row.error_code, error_message=row.error_message, segments=segments, created_at=row.created_at, updated_at=row.updated_at,
        )
