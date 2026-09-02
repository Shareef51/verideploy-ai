from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Uuid, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from verideploy.multimodal.video_evidence import (
    FrameObservation,
    TimelineEventKind,
    VideoEvidenceRecord,
    VideoKeyframe,
    VideoStatus,
    VideoTimelineEvent,
)


class Base(DeclarativeBase):
    pass


class VideoJobRow(Base):
    __tablename__ = "video_evidence_jobs"
    video_job_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False, index=True)
    ingestion_job_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    video_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float(), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    height: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    has_audio: Mapped[str | None] = mapped_column(String(5), nullable=True)
    transcription_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    frame_count: Mapped[int] = mapped_column(Integer(), default=0)
    timeline_event_count: Mapped[int] = mapped_column(Integer(), default=0)
    degradation_reasons_json: Mapped[str] = mapped_column(Text(), default="[]")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VideoFrameRow(Base):
    __tablename__ = "video_keyframes"
    frame_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    video_job_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("video_evidence_jobs.video_job_id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    timestamp_seconds: Mapped[float] = mapped_column(Float(), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer(), nullable=False)
    height: Mapped[int] = mapped_column(Integer(), nullable=False)
    selection_reason: Mapped[str] = mapped_column(String(120), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(40), nullable=False)
    observation_json: Mapped[str] = mapped_column(Text(), nullable=False)


class VideoTimelineRow(Base):
    __tablename__ = "video_timeline_events"
    event_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    video_job_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("video_evidence_jobs.video_job_id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    timestamp_seconds: Mapped[float] = mapped_column(Float(), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    statement: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text(), nullable=False)
    frame_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    transcript_segment_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    alignment_delta_seconds: Mapped[float | None] = mapped_column(Float(), nullable=True)


class SqlAlchemyVideoRepository:
    def __init__(self, database_url: str) -> None:
        kwargs: dict[str, object] = {"future": True}
        if database_url.startswith("sqlite") and ":memory:" in database_url:
            kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.engine = create_engine(database_url, **kwargs)
        if database_url.startswith("sqlite"):
            Base.metadata.create_all(self.engine)
        self._is_postgres = self.engine.dialect.name == "postgresql"
        self._lock = RLock()

    @contextmanager
    def _tenant_session(self, tenant_id: UUID):
        with Session(self.engine) as session:
            with session.begin():
                if self._is_postgres:
                    session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})
                yield session

    def get(self, tenant_id: UUID, video_job_id: UUID) -> VideoEvidenceRecord | None:
        with self._tenant_session(tenant_id) as session:
            row = session.scalar(select(VideoJobRow).where(VideoJobRow.tenant_id == tenant_id, VideoJobRow.video_job_id == video_job_id))
            return self._to_record(session, row) if row else None

    def create_or_get(self, record: VideoEvidenceRecord) -> tuple[VideoEvidenceRecord, bool]:
        with self._lock, self._tenant_session(record.tenant_id) as session:
            row = session.scalar(select(VideoJobRow).where(VideoJobRow.tenant_id == record.tenant_id, VideoJobRow.video_job_id == record.video_job_id).with_for_update())
            created = False
            if row is None:
                session.add(self._row(record)); created = True
        current = self.get(record.tenant_id, record.video_job_id)
        assert current is not None
        return current, created

    def mark_processing(self, tenant_id: UUID, video_job_id: UUID) -> None:
        with self._lock, self._tenant_session(tenant_id) as session:
            row = session.scalar(select(VideoJobRow).where(VideoJobRow.tenant_id == tenant_id, VideoJobRow.video_job_id == video_job_id).with_for_update())
            if row is None: raise KeyError("video job not found")
            row.status = VideoStatus.PROCESSING.value; row.updated_at = datetime.now(UTC)

    def complete(self, record: VideoEvidenceRecord) -> VideoEvidenceRecord:
        with self._lock, self._tenant_session(record.tenant_id) as session:
            row = session.scalar(select(VideoJobRow).where(VideoJobRow.tenant_id == record.tenant_id, VideoJobRow.video_job_id == record.video_job_id).with_for_update())
            if row is None: raise KeyError("video job not found")
            row.status = record.status.value; row.duration_seconds = record.duration_seconds; row.width = record.width; row.height = record.height
            row.has_audio = None if record.has_audio is None else str(record.has_audio).lower(); row.transcription_id = record.transcription_id
            row.frame_count = record.frame_count; row.timeline_event_count = record.timeline_event_count
            row.degradation_reasons_json = json.dumps(record.degradation_reasons, separators=(",", ":")); row.error_code = None; row.error_message = None; row.updated_at = record.updated_at
            for frame in record.keyframes:
                existing = session.get(VideoFrameRow, frame.frame_id)
                payload = self._frame_row(frame)
                if existing is None: session.add(payload)
                else:
                    for name in ("sequence_number","timestamp_seconds","sha256","width","height","selection_reason","object_ref","evidence_id","observation_json"):
                        setattr(existing, name, getattr(payload, name))
            for event in record.timeline:
                existing = session.get(VideoTimelineRow, event.event_id)
                payload = self._event_row(event)
                if existing is None: session.add(payload)
                else:
                    for name in ("sequence_number","timestamp_seconds","kind","statement","evidence_ids_json","frame_id","transcript_segment_id","alignment_delta_seconds"):
                        setattr(existing, name, getattr(payload, name))
        result = self.get(record.tenant_id, record.video_job_id); assert result is not None; return result

    def fail(self, tenant_id: UUID, video_job_id: UUID, *, error_code: str, error_message: str) -> None:
        with self._lock, self._tenant_session(tenant_id) as session:
            row = session.scalar(select(VideoJobRow).where(VideoJobRow.tenant_id == tenant_id, VideoJobRow.video_job_id == video_job_id).with_for_update())
            if row is None: raise KeyError("video job not found")
            row.status = VideoStatus.FAILED.value; row.error_code = error_code; row.error_message = error_message[:500]; row.updated_at = datetime.now(UTC)

    @staticmethod
    def _row(record: VideoEvidenceRecord) -> VideoJobRow:
        return VideoJobRow(video_job_id=record.video_job_id, tenant_id=record.tenant_id, ingestion_job_id=record.ingestion_job_id,
            correlation_id=record.correlation_id, video_sha256=record.video_sha256, status=record.status.value,
            duration_seconds=record.duration_seconds, width=record.width, height=record.height,
            has_audio=None if record.has_audio is None else str(record.has_audio).lower(), transcription_id=record.transcription_id,
            frame_count=record.frame_count, timeline_event_count=record.timeline_event_count,
            degradation_reasons_json=json.dumps(record.degradation_reasons, separators=(",", ":")), error_code=record.error_code,
            error_message=record.error_message, created_at=record.created_at, updated_at=record.updated_at)

    @staticmethod
    def _frame_row(frame: VideoKeyframe) -> VideoFrameRow:
        return VideoFrameRow(frame_id=frame.frame_id, video_job_id=frame.video_job_id, tenant_id=frame.tenant_id,
            sequence_number=frame.sequence_number, timestamp_seconds=frame.timestamp_seconds, sha256=frame.sha256,
            width=frame.width, height=frame.height, selection_reason=frame.selection_reason, object_ref=frame.object_ref,
            evidence_id=frame.evidence_id, observation_json=frame.observation.model_dump_json())

    @staticmethod
    def _event_row(event: VideoTimelineEvent) -> VideoTimelineRow:
        return VideoTimelineRow(event_id=event.event_id, video_job_id=event.video_job_id, tenant_id=event.tenant_id,
            sequence_number=event.sequence_number, timestamp_seconds=event.timestamp_seconds, kind=event.kind.value,
            statement=event.statement, evidence_ids_json=json.dumps(event.evidence_ids, separators=(",", ":")), frame_id=event.frame_id,
            transcript_segment_id=event.transcript_segment_id, alignment_delta_seconds=event.alignment_delta_seconds)

    @staticmethod
    def _to_record(session: Session, row: VideoJobRow) -> VideoEvidenceRecord:
        frame_rows = session.scalars(select(VideoFrameRow).where(VideoFrameRow.tenant_id == row.tenant_id, VideoFrameRow.video_job_id == row.video_job_id).order_by(VideoFrameRow.sequence_number)).all()
        event_rows = session.scalars(select(VideoTimelineRow).where(VideoTimelineRow.tenant_id == row.tenant_id, VideoTimelineRow.video_job_id == row.video_job_id).order_by(VideoTimelineRow.sequence_number)).all()
        frames = [VideoKeyframe(frame_id=f.frame_id, video_job_id=f.video_job_id, tenant_id=f.tenant_id, sequence_number=f.sequence_number,
            timestamp_seconds=f.timestamp_seconds, sha256=f.sha256, width=f.width, height=f.height, selection_reason=f.selection_reason,
            object_ref=f.object_ref, evidence_id=f.evidence_id, observation=FrameObservation.model_validate_json(f.observation_json)) for f in frame_rows]
        timeline = [VideoTimelineEvent(event_id=e.event_id, video_job_id=e.video_job_id, tenant_id=e.tenant_id, sequence_number=e.sequence_number,
            timestamp_seconds=e.timestamp_seconds, kind=TimelineEventKind(e.kind), statement=e.statement,
            evidence_ids=json.loads(e.evidence_ids_json), frame_id=e.frame_id, transcript_segment_id=e.transcript_segment_id,
            alignment_delta_seconds=e.alignment_delta_seconds) for e in event_rows]
        return VideoEvidenceRecord(video_job_id=row.video_job_id, tenant_id=row.tenant_id, ingestion_job_id=row.ingestion_job_id,
            correlation_id=row.correlation_id, video_sha256=row.video_sha256, status=VideoStatus(row.status), duration_seconds=row.duration_seconds,
            width=row.width, height=row.height, has_audio=None if row.has_audio is None else row.has_audio == "true", transcription_id=row.transcription_id,
            frame_count=row.frame_count, timeline_event_count=row.timeline_event_count, degradation_reasons=json.loads(row.degradation_reasons_json or "[]"),
            error_code=row.error_code, error_message=row.error_message, created_at=row.created_at, updated_at=row.updated_at,
            keyframes=frames, timeline=timeline)
