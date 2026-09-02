from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from services.ai.audio_transcription import get_audio_transcription_service
from verideploy.multimodal.audio_transcription import AudioTranscriptionRecord, AudioTranscriptionService

router = APIRouter(prefix="/internal/v1/audio/transcriptions", tags=["audio-transcription-internal"])


def _authorize(service_name: str) -> None:
    if service_name not in {"verideploy-gateway", "verideploy-multimodal-worker", "verideploy-investigation-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


@router.get("/{transcription_id}", response_model=AudioTranscriptionRecord)
def get_transcription(
    transcription_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID = Header(),
    service: AudioTranscriptionService = Depends(get_audio_transcription_service),
) -> AudioTranscriptionRecord:
    _authorize(x_internal_service)
    record = service.repository.get(x_tenant_id, transcription_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="audio transcription not found")
    return record
