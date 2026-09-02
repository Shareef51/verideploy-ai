from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
from services.ai.main import app
from verideploy.config import get_settings
from verideploy.multimodal.repository import SqlAlchemyIngestionRepository
from verideploy.multimodal.schemas import IngestionCommand
from verideploy.multimodal.service import IngestionService

def test_private_ingestion_job_requires_service_identity(tmp_path: Path, monkeypatch):
    db=f"sqlite+pysqlite:///{tmp_path/'api.db'}"; monkeypatch.setenv("DATABASE_URL",db); get_settings.cache_clear(); cmd=IngestionCommand(job_id=uuid4(),tenant_id=uuid4(),requested_by=uuid4(),correlation_id=uuid4(),idempotency_key="api-key-1234",modality="audio",original_filename="call.wav",detected_mime_type="audio/wav",size_bytes=100,sha256="d"*64,bucket="verideploy-evidence",object_key="tenants/t/call.wav"); service=IngestionService(SqlAlchemyIngestionRepository(db,create_schema=True)); job,_=service.accept(cmd); service.initialize(cmd.tenant_id,job.job_id)
    with TestClient(app) as client:
        denied=client.get(f"/internal/v1/ingestion/jobs/{job.job_id}",headers={"x-tenant-id":str(cmd.tenant_id)}); assert denied.status_code==403
        ok=client.get(f"/internal/v1/ingestion/jobs/{job.job_id}",headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(cmd.tenant_id)}); assert ok.status_code==200 and ok.json()["status"]=="READY"
        wrong=client.get(f"/internal/v1/ingestion/jobs/{job.job_id}",headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(uuid4())}); assert wrong.status_code==404
    get_settings.cache_clear()
