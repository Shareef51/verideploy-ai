from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from verideploy.multimodal.audio_repository import SqlAlchemyTranscriptionRepository
from verideploy.multimodal.audio_transcription import (
    AudioTranscriptionService, DeterministicTranscriptionProvider, ProviderTranscriptSegment, TranscriptRedactor,
)
from verideploy.multimodal.video_evidence import (
    CpuFrameAnalyzer, FFmpegVideoProcessor, LocalFrameArtifactStore, TimelineEventKind, VideoEvidenceCommand,
    VideoEvidenceService, VideoStatus, validate_video_bytes,
)
from verideploy.multimodal.video_repository import SqlAlchemyVideoRepository
from workers.multimodal.video_evidence_worker import VideoEvidenceJobCommand


def make_video(tmp_path: Path, *, audio: bool = True) -> bytes:
    out = tmp_path / ("sample-audio.mp4" if audio else "sample-silent.mp4")
    # Three distinct color sections ensure real scene changes. concat makes one video stream.
    filters = [
        "-f", "lavfi", "-i", "color=c=red:s=160x90:d=1:r=10",
        "-f", "lavfi", "-i", "color=c=green:s=160x90:d=1:r=10",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=1:r=10",
    ]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *filters]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=16000"]
    concat = "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]"
    cmd += ["-filter_complex", concat, "-map", "[v]"]
    if audio:
        cmd += ["-map", "3:a", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(cmd, check=True, timeout=30)
    return out.read_bytes()


def service(tmp_path: Path, *, transcribe: bool = True) -> VideoEvidenceService:
    video_repo = SqlAlchemyVideoRepository("sqlite+pysqlite:///:memory:")
    audio_service = None
    if transcribe:
        audio_repo = SqlAlchemyTranscriptionRepository("sqlite+pysqlite:///:memory:", create_schema=True)
        provider = DeterministicTranscriptionProvider([
            ProviderTranscriptSegment(start_seconds=0.15, end_seconds=0.55, text="checkout alert started", speaker="IC"),
            ProviderTranscriptSegment(start_seconds=1.7, end_seconds=2.2, text="rollback considered", speaker="SRE"),
        ])
        audio_service = AudioTranscriptionService(provider=provider, repository=audio_repo, redactor=TranscriptRedactor(), max_audio_bytes=20_000_000)
    return VideoEvidenceService(
        processor=FFmpegVideoProcessor(scene_threshold=0.1, interval_seconds=1.0, max_keyframes=10),
        repository=video_repo,
        frame_store=LocalFrameArtifactStore(str(tmp_path / "frames")),
        frame_analyzer=CpuFrameAnalyzer(),
        transcription_service=audio_service,
        max_video_bytes=20_000_000,
        max_duration_seconds=30,
        alignment_window_seconds=1.2,
    )


def command(video: bytes) -> VideoEvidenceCommand:
    return VideoEvidenceCommand(
        tenant_id=uuid4(), ingestion_job_id=uuid4(), correlation_id=uuid4(), original_filename="incident.mp4",
        declared_mime_type="video/mp4", video_bytes=video, transcription_model="deterministic-transcribe", language="en",
    )


def test_video_signature_validation(tmp_path: Path):
    video = make_video(tmp_path)
    result = validate_video_bytes(video, max_bytes=20_000_000)
    assert result.mime_type == "video/mp4"
    assert len(result.sha256) == 64
    with pytest.raises(ValueError):
        validate_video_bytes(b"not-video", max_bytes=100)


@pytest.mark.asyncio
async def test_ffmpeg_probe_audio_keyframes_exact_times(tmp_path: Path):
    video = make_video(tmp_path)
    processor = FFmpegVideoProcessor(scene_threshold=0.1, interval_seconds=1.0, max_keyframes=10)
    probe = await processor.probe(video)
    assert 2.5 <= probe.duration_seconds <= 3.2
    assert probe.width == 160 and probe.height == 90 and probe.has_audio
    audio = await processor.extract_audio(video)
    assert audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
    frames = await processor.extract_keyframes(video, probe)
    assert frames
    assert all(0 <= f.timestamp_seconds <= probe.duration_seconds for f in frames)
    assert [f.timestamp_seconds for f in frames] == sorted(f.timestamp_seconds for f in frames)
    assert any(f.selection_reason == "scene_change" for f in frames)


@pytest.mark.asyncio
async def test_full_video_pipeline_aligns_transcript_and_frames(tmp_path: Path):
    video = make_video(tmp_path)
    svc = service(tmp_path)
    cmd = command(video)
    progress: list[str] = []
    result = await svc.process(cmd, progress=lambda name, payload: _capture(progress, name))
    assert result.status == VideoStatus.COMPLETED
    assert result.frame_count > 0
    assert result.transcription_id is not None
    assert any(e.kind == TimelineEventKind.TRANSCRIPT_STATEMENT for e in result.timeline)
    assert any(e.kind == TimelineEventKind.FRAME_OBSERVATION for e in result.timeline)
    assert any(e.kind == TimelineEventKind.CROSS_MODAL_ALIGNMENT for e in result.timeline)
    assert [e.sequence_number for e in result.timeline] == list(range(1, len(result.timeline) + 1))
    assert "video.timeline.aligned" in progress


async def _capture(target: list[str], name: str) -> None:
    target.append(name)


@pytest.mark.asyncio
async def test_replay_is_idempotent(tmp_path: Path):
    video = make_video(tmp_path)
    svc = service(tmp_path)
    cmd = command(video)
    first = await svc.process(cmd)
    second = await svc.process(cmd)
    assert first.video_job_id == second.video_job_id
    assert [f.frame_id for f in first.keyframes] == [f.frame_id for f in second.keyframes]
    assert [e.event_id for e in first.timeline] == [e.event_id for e in second.timeline]


@pytest.mark.asyncio
async def test_silent_video_degrades_but_keeps_frame_timeline(tmp_path: Path):
    video = make_video(tmp_path, audio=False)
    svc = service(tmp_path)
    result = await svc.process(command(video))
    assert result.status == VideoStatus.PARTIAL
    assert "video_has_no_audio" in result.degradation_reasons
    assert result.keyframes
    assert all(e.kind == TimelineEventKind.FRAME_OBSERVATION for e in result.timeline)


@pytest.mark.asyncio
async def test_transcription_not_configured_degrades_gracefully(tmp_path: Path):
    video = make_video(tmp_path)
    svc = service(tmp_path, transcribe=False)
    result = await svc.process(command(video))
    assert result.status == VideoStatus.PARTIAL
    assert "transcription_not_configured" in result.degradation_reasons
    assert result.keyframes


@pytest.mark.asyncio
async def test_duration_limit_is_enforced(tmp_path: Path):
    video = make_video(tmp_path)
    svc = service(tmp_path)
    svc.max_duration_seconds = 1.0
    cmd = command(video)
    with pytest.raises(ValueError, match="duration"):
        await svc.process(cmd)
    record = svc.repository.get(cmd.tenant_id, svc.video_job_id(cmd.tenant_id, cmd.ingestion_job_id))
    assert record and record.status == VideoStatus.FAILED


def test_cross_tenant_repository_read_isolated(tmp_path: Path):
    video = make_video(tmp_path)
    svc = service(tmp_path)
    cmd = command(video)
    result = asyncio.run(svc.process(cmd))
    assert svc.repository.get(uuid4(), result.video_job_id) is None


def test_kafka_job_contract_contains_object_ref_not_video_bytes():
    payload = {
        "tenant_id": str(uuid4()), "ingestion_job_id": str(uuid4()), "correlation_id": str(uuid4()),
        "original_filename": "incident.mp4", "declared_mime_type": "video/mp4", "bucket": "verideploy-evidence",
        "object_key": "tenant/video.mp4", "transcription_model": "model-x",
    }
    parsed = VideoEvidenceJobCommand.model_validate(payload)
    assert parsed.object_key.endswith("video.mp4")
    with pytest.raises(ValidationError):
        VideoEvidenceJobCommand.model_validate({**payload, "video_bytes": "base64-should-never-be-on-kafka"})
