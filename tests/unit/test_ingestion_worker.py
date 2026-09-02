import json
from pathlib import Path
from uuid import uuid4
import pytest
from verideploy.multimodal.repository import SqlAlchemyIngestionRepository
from verideploy.multimodal.service import IngestionService
from workers.ingestion.ingestion_worker import handle_ingestion


def command():
    return {
        "job_id": str(uuid4()), "tenant_id": str(uuid4()), "requested_by": str(uuid4()), "correlation_id": str(uuid4()),
        "idempotency_key": "upload-key-0001", "modality": "document", "original_filename": "runbook.pdf",
        "detected_mime_type": "application/pdf", "size_bytes": 1024, "sha256": "a"*64,
        "bucket": "verideploy-evidence", "object_key": "tenants/t/evidence/runbook.pdf"
    }

@pytest.mark.asyncio
async def test_worker_persists_and_emits_ordered_lifecycle(tmp_path: Path):
    payload=command(); repo=SqlAlchemyIngestionRepository(f"sqlite+pysqlite:///{tmp_path/'ingestion.db'}",create_schema=True); service=IngestionService(repo); out=[]
    async def emit(t,p): out.append((t,p))
    await handle_ingestion(json.dumps(payload).encode(),service,emit)
    job=service.get(uuid4(), uuid4())
    stored=service.get(__import__('uuid').UUID(payload['tenant_id']),__import__('uuid').UUID(payload['job_id']))
    assert job is None
    assert stored is not None and stored.status.value=="READY" and stored.last_sequence_number==3
    assert [x[0] for x in out]==["ingestion.object.stored","ingestion.processing.started","ingestion.ready"]
    assert [x[1]["sequence_number"] for x in out]==[1,2,3]

@pytest.mark.asyncio
async def test_duplicate_command_replays_without_duplicate_rows(tmp_path: Path):
    payload=command(); repo=SqlAlchemyIngestionRepository(f"sqlite+pysqlite:///{tmp_path/'ingestion.db'}",create_schema=True); service=IngestionService(repo); first=[]; second=[]
    async def e1(t,p): first.append((t,p))
    async def e2(t,p): second.append((t,p))
    encoded=json.dumps(payload).encode(); await handle_ingestion(encoded,service,e1); await handle_ingestion(encoded,service,e2)
    assert len(first)==3 and len(second)==3
    assert [p["sequence_number"] for _,p in second]==[1,2,3]

@pytest.mark.asyncio
async def test_invalid_command_is_rejected(tmp_path: Path):
    repo=SqlAlchemyIngestionRepository(f"sqlite+pysqlite:///{tmp_path/'ingestion.db'}",create_schema=True); service=IngestionService(repo); out=[]
    async def emit(t,p): out.append((t,p))
    await handle_ingestion(b'{"job_id":"bad"}',service,emit)
    assert out==[("ingestion.command.rejected",{"reason":"schema_validation_failed"})]
