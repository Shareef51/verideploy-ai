import os
from uuid import uuid4

os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient
from services.ai.main import app
from services.ai.routes.releases import get_release_risk_service
from verideploy.releases.repository import SqlAlchemyReleaseRiskRepository
from verideploy.releases.schemas import ReleaseRiskCommand, ReleaseRiskPolicyInput
from verideploy.releases.service import ReleaseRiskService


def test_private_status_api_enforces_service_identity(tmp_path, monkeypatch) -> None:
    db = tmp_path / "api.db"
    monkeypatch.setenv("RELEASE_RISK_DATABASE_URL", f"sqlite:///{db}")
    get_release_risk_service.cache_clear()
    tenant_id, assessment_id = uuid4(), uuid4()
    service = ReleaseRiskService(SqlAlchemyReleaseRiskRepository(f"sqlite:///{db}", create_schema=True))
    record, _ = service.accept(ReleaseRiskCommand(assessment_id=assessment_id, tenant_id=tenant_id, requested_by=uuid4(), idempotency_key="api-risk-001", repository="nexuspay/payment-service", release_id="v4.8.2", commit_sha="a1b2c3d4", policy=ReleaseRiskPolicyInput(changed_files=25, changed_services=1)))
    service.assess(record.tenant_id, record.assessment_id)
    with TestClient(app) as client:
        denied = client.get(f"/internal/v1/releases/assessments/{assessment_id}", headers={"x-tenant-id": str(tenant_id)})
        assert denied.status_code == 401
        accepted = client.get(f"/internal/v1/releases/assessments/{assessment_id}", headers={"x-internal-service": "verideploy-gateway", "x-tenant-id": str(tenant_id)})
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "COMPLETED"
