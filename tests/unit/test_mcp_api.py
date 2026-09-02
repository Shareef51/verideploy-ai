from uuid import uuid4

from fastapi.testclient import TestClient

from services.ai.main import app
from services.ai.mcp_gateway import get_mcp_gateway
from verideploy.mcp.contracts import MCPPermission
from tests.unit.test_mcp_gateway import build


def test_mcp_private_api_auth_and_invoke():
    gateway, *_ = build()
    app.dependency_overrides[get_mcp_gateway] = lambda: gateway
    tenant = uuid4()
    try:
        with TestClient(app) as client:
            payload = {"tool_name":"knowledge.search","arguments":{"query":"runbook"},"correlation_id":"corr","permissions":[MCPPermission.KNOWLEDGE_READ.value]}
            r = client.post("/internal/v1/mcp/invoke", json=payload, headers={"x-internal-service":"bad","x-tenant-id":str(tenant),"x-user-id":"alice"})
            assert r.status_code == 401
            r = client.post("/internal/v1/mcp/invoke", json=payload, headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(tenant),"x-user-id":"alice"})
            assert r.status_code == 200
            assert r.json()["tool_name"] == "knowledge.search"
    finally:
        app.dependency_overrides.clear()
