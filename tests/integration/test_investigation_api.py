import os
from uuid import uuid4

os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient
from services.ai.main import app
from services.ai.routes.investigations import get_investigation_service
from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.schemas import CreateInvestigationCommand
from verideploy.investigations.service import InvestigationService


def test_private_snapshot_and_replay_api_enforce_service_identity_and_tenant(tmp_path, monkeypatch) -> None:
    db = tmp_path / "incident-api.db"
    monkeypatch.setenv("INVESTIGATION_DATABASE_URL", f"sqlite:///{db}")
    get_investigation_service.cache_clear()
    service = InvestigationService(SqlAlchemyInvestigationRepository(f"sqlite:///{db}", create_schema=True))
    command = CreateInvestigationCommand(investigation_id=uuid4(), tenant_id=uuid4(), requested_by=uuid4(), idempotency_key="incident-api-001", query="Why did checkout latency increase after the release?")
    record,_=service.accept(command); service.initialize(record.tenant_id,record.investigation_id)
    trusted={"x-internal-service":"verideploy-gateway","x-tenant-id":str(record.tenant_id)}
    with TestClient(app) as client:
        assert client.get(f"/internal/v1/investigations/{record.investigation_id}",headers={"x-tenant-id":str(record.tenant_id)}).status_code == 401
        snapshot=client.get(f"/internal/v1/investigations/{record.investigation_id}",headers=trusted)
        assert snapshot.status_code == 200 and snapshot.json()["last_sequence_number"] == 3
        replay=client.get(f"/internal/v1/investigations/{record.investigation_id}/events?after_sequence=1",headers=trusted)
        assert [e["sequence_number"] for e in replay.json()] == [2,3]
        foreign=client.get(f"/internal/v1/investigations/{record.investigation_id}",headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(uuid4())})
        assert foreign.status_code == 404
