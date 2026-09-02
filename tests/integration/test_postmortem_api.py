import os
from uuid import uuid4
from fastapi.testclient import TestClient
from tests.unit.test_postmortems import stack, completed_investigation, command
from verideploy.postmortems.schemas import ApprovalDecision, ReviewPostmortemCommand


def test_private_postmortem_api_enforces_identity_and_tenant(tmp_path, monkeypatch):
    db=f"sqlite:///{tmp_path/'api.db'}"; monkeypatch.setenv("INVESTIGATION_DATABASE_URL",db); monkeypatch.setenv("POSTMORTEM_DATABASE_URL",db)
    from services.ai.routes.investigations import get_investigation_service
    from services.ai.routes.postmortems import get_postmortem_service
    get_investigation_service.cache_clear(); get_postmortem_service.cache_clear()
    investigations=get_investigation_service(); service=get_postmortem_service(); tenant,user=uuid4(),uuid4(); inv=completed_investigation(investigations,tenant,user); record,_=service.create(command(inv,user))
    from services.ai.main import app
    client=TestClient(app)
    assert client.get(f"/internal/v1/postmortems/{record.postmortem_id}",headers={"x-tenant-id":str(tenant)}).status_code==401
    headers={"x-tenant-id":str(tenant),"x-internal-service":"verideploy-gateway"}
    assert client.get(f"/internal/v1/postmortems/{record.postmortem_id}",headers=headers).status_code==200
    assert client.get(f"/internal/v1/postmortems/{record.postmortem_id}",headers={"x-tenant-id":str(uuid4()),"x-internal-service":"verideploy-gateway"}).status_code==404
