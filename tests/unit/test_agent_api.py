from uuid import uuid4

from fastapi.testclient import TestClient

from services.ai.main import app
from services.ai.agents import get_planning_agent, get_supervisor_agent
from verideploy.agents.contracts import AgentPlan, PlanStep, SupervisorDecision


class SupervisorStub:
    async def run(self, request, *, authorization):
        return SupervisorDecision(route="github", rationale="bounded read", confidence=0.9, required_permissions=[])


class PlannerStub:
    async def run(self, request, *, authorization, max_total_tool_calls):
        return AgentPlan(rationale="one read", steps=[PlanStep(step_id="step-01", agent="github", objective="inspect repository", max_tool_calls=1)])


def _payload(tenant, user="u1"):
    return {"request":{"tenant_id":str(tenant),"user_id":user,"correlation_id":"corr","objective":"inspect repo","context":{}},"permissions":[]}


def test_private_agent_endpoints_enforce_service_tenant_and_user_scope():
    tenant=uuid4(); app.dependency_overrides[get_supervisor_agent]=lambda: SupervisorStub(); app.dependency_overrides[get_planning_agent]=lambda: PlannerStub()
    try:
        client=TestClient(app)
        assert client.post('/internal/v1/agents/supervise',json=_payload(tenant),headers={'x-tenant-id':str(tenant),'x-user-id':'u1'}).status_code == 401
        assert client.post('/internal/v1/agents/supervise',json=_payload(tenant),headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(uuid4()),'x-user-id':'u1'}).status_code == 403
        assert client.post('/internal/v1/agents/plan',json=_payload(tenant),headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(tenant),'x-user-id':'wrong'}).status_code == 403
        ok=client.post('/internal/v1/agents/plan',json=_payload(tenant),headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(tenant),'x-user-id':'u1'})
        assert ok.status_code == 200 and ok.json()['steps'][0]['step_id'] == 'step-01'
    finally:
        app.dependency_overrides.clear()
