from pathlib import Path
from uuid import uuid4
from verideploy.multimodal.repository import SqlAlchemyIngestionRepository
from verideploy.multimodal.schemas import IngestionCommand
from verideploy.multimodal.service import IngestionService


def make(tenant=None,key="ingest-key-1234"):
    return IngestionCommand(job_id=uuid4(),tenant_id=tenant or uuid4(),requested_by=uuid4(),correlation_id=uuid4(),idempotency_key=key,modality="image",original_filename="dashboard.png",detected_mime_type="image/png",size_bytes=44,sha256="b"*64,bucket="verideploy-evidence",object_key=f"tenants/x/{uuid4()}.png")

def test_tenant_isolation_and_event_replay(tmp_path: Path):
    repo=SqlAlchemyIngestionRepository(f"sqlite+pysqlite:///{tmp_path/'repo.db'}",create_schema=True); service=IngestionService(repo); cmd=make(); job,_=service.accept(cmd); service.initialize(cmd.tenant_id,job.job_id)
    assert service.get(uuid4(),job.job_id) is None
    assert [e.sequence_number for e in service.events(cmd.tenant_id,job.job_id,after_sequence=1)]==[2,3]

def test_idempotency_is_tenant_scoped(tmp_path: Path):
    repo=SqlAlchemyIngestionRepository(f"sqlite+pysqlite:///{tmp_path/'repo.db'}",create_schema=True); service=IngestionService(repo); tenant=uuid4(); one=make(tenant,"same-key-123"); two=make(tenant,"same-key-123")
    j1,c1=service.accept(one); j2,c2=service.accept(two)
    assert c1 is True and c2 is False and j1.job_id==j2.job_id
