from __future__ import annotations

import os
from functools import lru_cache

from services.ai.audio_transcription import get_audio_transcription_service
from verideploy.config import get_settings
from verideploy.multimodal.video_evidence import CpuFrameAnalyzer, FFmpegVideoProcessor, LocalFrameArtifactStore, VideoEvidenceService
from verideploy.multimodal.video_repository import SqlAlchemyVideoRepository


@lru_cache
def get_video_evidence_service() -> VideoEvidenceService:
    settings = get_settings()
    database_url = os.getenv("VIDEO_DATABASE_URL") or settings.database_url
    repository = SqlAlchemyVideoRepository(database_url)
    transcription_service = None
    if settings.openai_transcription_model or settings.app_env == "test" or settings.ai_provider == "test":
        transcription_service = get_audio_transcription_service()
    return VideoEvidenceService(
        processor=FFmpegVideoProcessor(
            scene_threshold=settings.video_scene_threshold,
            interval_seconds=settings.video_keyframe_interval_seconds,
            max_keyframes=settings.video_max_keyframes,
        ),
        repository=repository,
        frame_store=LocalFrameArtifactStore(settings.video_frame_root),
        frame_analyzer=CpuFrameAnalyzer(),
        transcription_service=transcription_service,
        max_video_bytes=settings.max_video_upload_bytes,
        max_duration_seconds=settings.video_max_duration_seconds,
        alignment_window_seconds=settings.video_alignment_window_seconds,
    )
