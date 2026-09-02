from __future__ import annotations
from fastapi.testclient import TestClient
from services.ai.main import app
from services.ai.routes.integrations import get_engineering_integrations
from verideploy.config import Settings
from verideploy.integrations.factory import create_engineering_integrations


def _deps():
    settings=Settings(app_env="test",ai_provider="test",github_api_token=None,jira_base_url=None,jira_api_token=None,prometheus_base_url=None,grafana_base_url=None,tempo_base_url=None,loki_base_url=None)
    return create_engineering_integrations(settings)

def test_integration_status_requires_trusted_service_and_reports_unconfigured_explicitly():
    app.dependency_overrides[get_engineering_integrations]=_deps
    c=TestClient(app)
    assert c.get('/internal/v1/integrations/status').status_code==401
    r=c.get('/internal/v1/integrations/status',headers={'x-internal-service':'verideploy-gateway'})
    assert r.status_code==200
    data={x['source']:x['configured'] for x in r.json()['integrations']}
    assert data=={'github':False,'jira':False,'prometheus':False,'grafana':False,'trace':False,'log':False}
    app.dependency_overrides.clear()
