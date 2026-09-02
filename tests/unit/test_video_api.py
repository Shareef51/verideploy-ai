from uuid import uuid4

from fastapi.testclient import TestClient

from services.ai.main import app
from services.ai.routes.video_evidence import get_video_evidence_service
from verideploy.multimodal.video_evidence import CpuFrameAnalyzer, FFmpegVideoProcessor, LocalFrameArtifactStore, VideoEvidenceService
from verideploy.multimodal.video_repository import SqlAlchemyVideoRepository


def _service(tmp_path):
    return VideoEvidenceService(processor=FFmpegVideoProcessor(), repository=SqlAlchemyVideoRepository("sqlite+pysqlite:///:memory:"),
        frame_store=LocalFrameArtifactStore(str(tmp_path)), frame_analyzer=CpuFrameAnalyzer(), transcription_service=None,
        max_video_bytes=10_000_000, max_duration_seconds=60)


def test_private_video_route_requires_trusted_service(tmp_path):
    svc = _service(tmp_path)
    app.dependency_overrides[get_video_evidence_service] = lambda: svc
    try:
        client = TestClient(app)
        response = client.get(f"/internal/v1/video/evidence/{uuid4()}", headers={"x-tenant-id": str(uuid4())})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
