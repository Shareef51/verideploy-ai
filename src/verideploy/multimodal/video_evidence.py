from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from PIL import Image, ImageFilter, ImageStat
from pydantic import BaseModel, ConfigDict, Field, model_validator

from verideploy.multimodal.audio_transcription import (
    AudioTranscriptionCommand,
    AudioTranscriptionRecord,
    AudioTranscriptionService,
    TranscriptionStatus,
)


class VideoStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class TimelineEventKind(StrEnum):
    FRAME_OBSERVATION = "frame_observation"
    TRANSCRIPT_STATEMENT = "transcript_statement"
    CROSS_MODAL_ALIGNMENT = "cross_modal_alignment"


class VideoValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mime_type: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class VideoProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration_seconds: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    has_audio: bool
    video_codec: str | None = None
    audio_codec: str | None = None


class ExtractedFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    timestamp_seconds: float = Field(ge=0)
    image_bytes: bytes = Field(min_length=1, exclude=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    selection_reason: str = Field(min_length=1, max_length=120)


class FrameObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=1200)
    mean_luminance: float = Field(ge=0, le=255)
    edge_density: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    analysis_mode: str = Field(min_length=1, max_length=80)


class VideoKeyframe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame_id: UUID
    video_job_id: UUID
    tenant_id: UUID
    sequence_number: int = Field(ge=1)
    timestamp_seconds: float = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    selection_reason: str
    object_ref: str = Field(min_length=1, max_length=1024)
    evidence_id: str = Field(pattern=r"^VD-VIDEO-[A-F0-9]{12}$")
    observation: FrameObservation


class VideoTimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    video_job_id: UUID
    tenant_id: UUID
    sequence_number: int = Field(ge=1)
    timestamp_seconds: float = Field(ge=0)
    kind: TimelineEventKind
    statement: str = Field(min_length=1, max_length=2400)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    frame_id: UUID | None = None
    transcript_segment_id: UUID | None = None
    alignment_delta_seconds: float | None = Field(default=None, ge=0)


class VideoEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_job_id: UUID
    tenant_id: UUID
    ingestion_job_id: UUID
    correlation_id: UUID
    video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: VideoStatus
    duration_seconds: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    has_audio: bool | None = None
    transcription_id: UUID | None = None
    frame_count: int = Field(default=0, ge=0)
    timeline_event_count: int = Field(default=0, ge=0)
    degradation_reasons: list[str] = Field(default_factory=list, max_length=20)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    keyframes: list[VideoKeyframe] = Field(default_factory=list)
    timeline: list[VideoTimelineEvent] = Field(default_factory=list)


class VideoEvidenceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    ingestion_job_id: UUID
    correlation_id: UUID
    original_filename: str = Field(min_length=1, max_length=255)
    declared_mime_type: str = Field(min_length=3, max_length=120)
    video_bytes: bytes = Field(min_length=1)
    transcription_model: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, min_length=2, max_length=20)


class VideoRepository(Protocol):
    def get(self, tenant_id: UUID, video_job_id: UUID) -> VideoEvidenceRecord | None: ...
    def create_or_get(self, record: VideoEvidenceRecord) -> tuple[VideoEvidenceRecord, bool]: ...
    def mark_processing(self, tenant_id: UUID, video_job_id: UUID) -> None: ...
    def complete(self, record: VideoEvidenceRecord) -> VideoEvidenceRecord: ...
    def fail(self, tenant_id: UUID, video_job_id: UUID, *, error_code: str, error_message: str) -> None: ...


class FrameArtifactStore(Protocol):
    async def put_frame(self, *, tenant_id: UUID, video_job_id: UUID, frame_id: UUID, image_bytes: bytes) -> str: ...


class LocalFrameArtifactStore:
    def __init__(self, root: str = "data/processed/video_frames") -> None:
        self.root = Path(root)

    async def put_frame(self, *, tenant_id: UUID, video_job_id: UUID, frame_id: UUID, image_bytes: bytes) -> str:
        path = self.root / str(tenant_id) / str(video_job_id) / f"{frame_id}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, image_bytes)
        return path.as_posix()


class FrameAnalyzer(Protocol):
    async def analyze(self, frame: ExtractedFrame) -> FrameObservation: ...


class CpuFrameAnalyzer:
    """CPU-safe direct visual descriptor. It does not claim semantic VLM understanding."""

    async def analyze(self, frame: ExtractedFrame) -> FrameObservation:
        def _analyze() -> FrameObservation:
            with Image.open(io.BytesIO(frame.image_bytes)) as image:
                gray = image.convert("L")
                stat = ImageStat.Stat(gray)
                mean = float(stat.mean[0])
                edges = gray.filter(ImageFilter.FIND_EDGES)
                edge_hist = edges.histogram()
                total = max(1, sum(edge_hist))
                strong = sum(edge_hist[96:])
                density = min(1.0, strong / total)
                summary = (
                    f"Direct frame observation at {frame.timestamp_seconds:.3f}s: "
                    f"mean luminance {mean:.1f}/255 and edge density {density:.3f}. "
                    "No semantic cause is inferred by the CPU fallback."
                )
                return FrameObservation(
                    summary=summary,
                    mean_luminance=mean,
                    edge_density=density,
                    confidence=0.98,
                    analysis_mode="cpu_visual_signature",
                )
        return await asyncio.to_thread(_analyze)


class FFmpegVideoProcessor:
    def __init__(
        self,
        *,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        scene_threshold: float = 0.35,
        interval_seconds: float = 10.0,
        max_keyframes: int = 60,
    ) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.scene_threshold = scene_threshold
        self.interval_seconds = interval_seconds
        self.max_keyframes = max_keyframes
        if not shutil.which(ffmpeg_bin) or not shutil.which(ffprobe_bin):
            raise RuntimeError("ffmpeg and ffprobe are required for video processing")

    async def probe(self, video_bytes: bytes) -> VideoProbe:
        return await asyncio.to_thread(self._probe_sync, video_bytes)

    def _probe_sync(self, video_bytes: bytes) -> VideoProbe:
        with tempfile.TemporaryDirectory(prefix="verideploy-video-probe-") as tmp:
            path = Path(tmp) / "input.mp4"
            path.write_bytes(video_bytes)
            proc = subprocess.run(
                [self.ffprobe_bin, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                check=False, capture_output=True, text=True, timeout=30,
            )
            if proc.returncode != 0:
                raise ValueError("ffprobe could not parse the video")
            data = json.loads(proc.stdout)
            video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
            if not video_stream:
                raise ValueError("video stream is missing")
            audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
            duration = float(data.get("format", {}).get("duration") or video_stream.get("duration") or 0)
            if duration <= 0:
                raise ValueError("video duration is unavailable")
            return VideoProbe(
                duration_seconds=duration,
                width=int(video_stream.get("width") or 0),
                height=int(video_stream.get("height") or 0),
                has_audio=audio_stream is not None,
                video_codec=video_stream.get("codec_name"),
                audio_codec=audio_stream.get("codec_name") if audio_stream else None,
            )

    async def extract_audio(self, video_bytes: bytes) -> bytes:
        return await asyncio.to_thread(self._extract_audio_sync, video_bytes)

    def _extract_audio_sync(self, video_bytes: bytes) -> bytes:
        with tempfile.TemporaryDirectory(prefix="verideploy-video-audio-") as tmp:
            input_path = Path(tmp) / "input.mp4"
            output_path = Path(tmp) / "audio.wav"
            input_path.write_bytes(video_bytes)
            proc = subprocess.run(
                [self.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output_path)],
                check=False, capture_output=True, timeout=120,
            )
            if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 44:
                raise ValueError("audio extraction failed")
            return output_path.read_bytes()

    async def extract_keyframes(self, video_bytes: bytes, probe: VideoProbe) -> list[ExtractedFrame]:
        return await asyncio.to_thread(self._extract_keyframes_sync, video_bytes, probe)

    def _extract_keyframes_sync(self, video_bytes: bytes, probe: VideoProbe) -> list[ExtractedFrame]:
        with tempfile.TemporaryDirectory(prefix="verideploy-video-frames-") as tmp:
            base = Path(tmp)
            input_path = base / "input.mp4"
            scene_dir = base / "scene"
            interval_dir = base / "interval"
            scene_dir.mkdir(); interval_dir.mkdir()
            input_path.write_bytes(video_bytes)
            scene_pattern = str(scene_dir / "%06d.jpg")
            scene_filter = f"select='gt(scene,{self.scene_threshold})',showinfo"
            scene_proc = subprocess.run(
                [self.ffmpeg_bin, "-hide_banner", "-loglevel", "info", "-y", "-i", str(input_path), "-vf", scene_filter, "-fps_mode", "vfr", "-q:v", "3", scene_pattern],
                check=False, capture_output=True, text=True, timeout=180,
            )
            # Interval frames guarantee coverage even when scene detection yields none.
            interval_pattern = str(interval_dir / "%06d.jpg")
            subprocess.run(
                [self.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path), "-vf", f"fps=1/{self.interval_seconds}", "-q:v", "3", interval_pattern],
                check=False, capture_output=True, timeout=180,
            )
            candidates: list[tuple[float, Path, str]] = []
            scene_files = sorted(scene_dir.glob("*.jpg"))
            scene_times = [float(value) for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", scene_proc.stderr or "")]
            if len(scene_times) != len(scene_files):
                raise ValueError("unable to recover exact scene-frame timestamps from ffmpeg")
            candidates.extend((timestamp, path, "scene_change") for timestamp, path in zip(scene_times, scene_files, strict=True))
            interval_files = sorted(interval_dir.glob("*.jpg"))
            candidates.extend((min(i * self.interval_seconds, probe.duration_seconds), p, "interval") for i, p in enumerate(interval_files))
            if not candidates:
                raise ValueError("keyframe extraction produced no frames")
            candidates.sort(key=lambda item: (item[0], 0 if item[2] == "scene_change" else 1))
            unique: list[tuple[float, Path, str]] = []
            for item in candidates:
                if unique and abs(item[0] - unique[-1][0]) < 0.35:
                    if unique[-1][2] == "interval" and item[2] == "scene_change":
                        unique[-1] = item
                    continue
                unique.append(item)
            if len(unique) > self.max_keyframes:
                stride = max(1, math.ceil(len(unique) / self.max_keyframes))
                unique = unique[::stride][: self.max_keyframes]
            result: list[ExtractedFrame] = []
            for timestamp, path, reason in unique:
                data = path.read_bytes()
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
                result.append(ExtractedFrame(
                    timestamp_seconds=round(max(0.0, timestamp), 3), image_bytes=data,
                    sha256=hashlib.sha256(data).hexdigest(), width=width, height=height,
                    selection_reason=reason,
                ))
            return result


def validate_video_bytes(video_bytes: bytes, *, max_bytes: int) -> VideoValidationResult:
    if not video_bytes:
        raise ValueError("video payload is empty")
    if len(video_bytes) > max_bytes:
        raise ValueError("video exceeds configured size limit")
    if len(video_bytes) < 12 or video_bytes[4:8] != b"ftyp":
        raise ValueError("unsupported or invalid video signature")
    return VideoValidationResult(mime_type="video/mp4", sha256=hashlib.sha256(video_bytes).hexdigest())


Progress = Callable[[str, dict[str, object]], Awaitable[None]]


class VideoEvidenceService:
    def __init__(
        self,
        *,
        processor: FFmpegVideoProcessor,
        repository: VideoRepository,
        frame_store: FrameArtifactStore,
        frame_analyzer: FrameAnalyzer,
        transcription_service: AudioTranscriptionService | None,
        max_video_bytes: int,
        max_duration_seconds: float,
        alignment_window_seconds: float = 5.0,
    ) -> None:
        self.processor = processor
        self.repository = repository
        self.frame_store = frame_store
        self.frame_analyzer = frame_analyzer
        self.transcription_service = transcription_service
        self.max_video_bytes = max_video_bytes
        self.max_duration_seconds = max_duration_seconds
        self.alignment_window_seconds = alignment_window_seconds

    @staticmethod
    def video_job_id(tenant_id: UUID, ingestion_job_id: UUID) -> UUID:
        return uuid5(NAMESPACE_URL, f"verideploy:video:{tenant_id}:{ingestion_job_id}")

    async def process(self, command: VideoEvidenceCommand, progress: Progress | None = None) -> VideoEvidenceRecord:
        async def emit(name: str, payload: dict[str, object]) -> None:
            if progress:
                await progress(name, payload)

        validation = validate_video_bytes(command.video_bytes, max_bytes=self.max_video_bytes)
        job_id = self.video_job_id(command.tenant_id, command.ingestion_job_id)
        existing = self.repository.get(command.tenant_id, job_id)
        if existing and existing.status in {VideoStatus.COMPLETED, VideoStatus.PARTIAL}:
            if existing.video_sha256 != validation.sha256:
                raise ValueError("idempotent video identity refers to different content")
            return existing
        now = datetime.now(UTC)
        seed = VideoEvidenceRecord(
            video_job_id=job_id, tenant_id=command.tenant_id, ingestion_job_id=command.ingestion_job_id,
            correlation_id=command.correlation_id, video_sha256=validation.sha256, status=VideoStatus.PENDING,
            created_at=now, updated_at=now,
        )
        current, _ = self.repository.create_or_get(seed)
        if current.video_sha256 != validation.sha256:
            raise ValueError("idempotent video identity refers to different content")
        self.repository.mark_processing(command.tenant_id, job_id)
        await emit("video.processing.started", {"video_job_id": str(job_id)})

        try:
            probe = await self.processor.probe(command.video_bytes)
        except Exception:
            self.repository.fail(command.tenant_id, job_id, error_code="probe_failed", error_message="video probe failed")
            raise
        if probe.duration_seconds > self.max_duration_seconds:
            self.repository.fail(command.tenant_id, job_id, error_code="duration_limit", error_message="video duration exceeds policy")
            raise ValueError("video duration exceeds configured limit")
        await emit("video.probe.completed", probe.model_dump())

        degradation: list[str] = []
        transcription: AudioTranscriptionRecord | None = None
        frames: list[VideoKeyframe] = []

        if probe.has_audio and self.transcription_service and command.transcription_model:
            try:
                audio_bytes = await self.processor.extract_audio(command.video_bytes)
                await emit("video.audio.extracted", {"bytes": len(audio_bytes)})
                transcription = await self.transcription_service.transcribe(AudioTranscriptionCommand(
                    tenant_id=command.tenant_id, ingestion_job_id=command.ingestion_job_id,
                    correlation_id=command.correlation_id, original_filename=f"{Path(command.original_filename).stem}.wav",
                    declared_mime_type="audio/wav", audio_bytes=audio_bytes, model=command.transcription_model,
                    language=command.language,
                ))
                if transcription.status is not TranscriptionStatus.COMPLETED:
                    degradation.append("transcription_incomplete")
                await emit("video.transcription.completed", {"transcription_id": str(transcription.transcription_id), "segments": len(transcription.segments)})
            except Exception:
                degradation.append("audio_transcription_failed")
                await emit("video.transcription.failed", {"video_job_id": str(job_id)})
        elif probe.has_audio:
            degradation.append("transcription_not_configured")
        else:
            degradation.append("video_has_no_audio")

        try:
            extracted = await self.processor.extract_keyframes(command.video_bytes, probe)
            await emit("video.keyframes.extracted", {"count": len(extracted)})
            for seq, frame in enumerate(extracted, 1):
                frame_id = uuid5(NAMESPACE_URL, f"verideploy:video-frame:{job_id}:{frame.timestamp_seconds:.3f}:{frame.sha256}")
                object_ref = await self.frame_store.put_frame(
                    tenant_id=command.tenant_id, video_job_id=job_id, frame_id=frame_id, image_bytes=frame.image_bytes
                )
                observation = await self.frame_analyzer.analyze(frame)
                evidence_id = f"VD-VIDEO-{hashlib.sha256(str(frame_id).encode()).hexdigest()[:12].upper()}"
                frames.append(VideoKeyframe(
                    frame_id=frame_id, video_job_id=job_id, tenant_id=command.tenant_id, sequence_number=seq,
                    timestamp_seconds=frame.timestamp_seconds, sha256=frame.sha256, width=frame.width, height=frame.height,
                    selection_reason=frame.selection_reason, object_ref=object_ref, evidence_id=evidence_id, observation=observation,
                ))
            await emit("video.frames.analyzed", {"count": len(frames)})
        except Exception:
            degradation.append("keyframe_processing_failed")
            await emit("video.keyframes.failed", {"video_job_id": str(job_id)})

        if not frames and (transcription is None or not transcription.segments):
            self.repository.fail(command.tenant_id, job_id, error_code="all_modalities_failed", error_message="video processing produced no usable evidence")
            raise RuntimeError("video processing produced no usable evidence")

        timeline = self._build_timeline(job_id, command.tenant_id, frames, transcription)
        await emit("video.timeline.aligned", {"events": len(timeline)})
        status = VideoStatus.PARTIAL if degradation else VideoStatus.COMPLETED
        completed = seed.model_copy(update={
            "status": status, "duration_seconds": probe.duration_seconds, "width": probe.width, "height": probe.height,
            "has_audio": probe.has_audio, "transcription_id": transcription.transcription_id if transcription else None,
            "frame_count": len(frames), "timeline_event_count": len(timeline), "degradation_reasons": degradation,
            "keyframes": frames, "timeline": timeline, "updated_at": datetime.now(UTC),
        })
        stored = self.repository.complete(completed)
        await emit("video.processing.partial" if status is VideoStatus.PARTIAL else "video.processing.completed", {
            "video_job_id": str(job_id), "status": status.value, "frame_count": len(frames), "timeline_event_count": len(timeline),
            "degradation_reasons": degradation,
        })
        return stored

    def _build_timeline(
        self, job_id: UUID, tenant_id: UUID, frames: list[VideoKeyframe], transcription: AudioTranscriptionRecord | None
    ) -> list[VideoTimelineEvent]:
        raw: list[tuple[float, TimelineEventKind, str, list[str], UUID | None, UUID | None, float | None]] = []
        for frame in frames:
            raw.append((frame.timestamp_seconds, TimelineEventKind.FRAME_OBSERVATION, frame.observation.summary, [frame.evidence_id], frame.frame_id, None, None))
        segments = transcription.segments if transcription else []
        for seg in segments:
            midpoint = (seg.start_seconds + seg.end_seconds) / 2
            speaker = f"{seg.speaker}: " if seg.speaker else ""
            raw.append((midpoint, TimelineEventKind.TRANSCRIPT_STATEMENT, f"{speaker}{seg.text}", [seg.evidence_id], None, seg.segment_id, None))
            if frames:
                nearest = min(frames, key=lambda f: abs(f.timestamp_seconds - midpoint))
                delta = abs(nearest.timestamp_seconds - midpoint)
                if delta <= self.alignment_window_seconds:
                    raw.append((
                        midpoint, TimelineEventKind.CROSS_MODAL_ALIGNMENT,
                        f"Transcript segment aligned with nearest extracted frame within {delta:.3f}s.",
                        [seg.evidence_id, nearest.evidence_id], nearest.frame_id, seg.segment_id, round(delta, 3),
                    ))
        raw.sort(key=lambda item: (item[0], item[1].value, ",".join(item[3])))
        events: list[VideoTimelineEvent] = []
        for seq, item in enumerate(raw, 1):
            timestamp, kind, statement, evidence_ids, frame_id, segment_id, delta = item
            event_id = uuid5(NAMESPACE_URL, f"verideploy:video-event:{job_id}:{kind.value}:{timestamp:.3f}:{':'.join(evidence_ids)}")
            events.append(VideoTimelineEvent(
                event_id=event_id, video_job_id=job_id, tenant_id=tenant_id, sequence_number=seq,
                timestamp_seconds=round(timestamp, 3), kind=kind, statement=statement, evidence_ids=evidence_ids,
                frame_id=frame_id, transcript_segment_id=segment_id, alignment_delta_seconds=delta,
            ))
        return events
