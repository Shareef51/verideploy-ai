from __future__ import annotations
import os,time
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.ai.middleware.internal_service_auth import InternalServiceAuthMiddleware, sign_internal_request
from verideploy.config import get_settings
ROOT=Path(__file__).resolve().parents[2]

def test_hmac_service_auth_rejects_unsigned_when_required(monkeypatch):
    monkeypatch.setenv('APP_ENV','test');monkeypatch.setenv('INTERNAL_SERVICE_AUTH_REQUIRED','true');monkeypatch.setenv('INTERNAL_SERVICE_AUTH_SECRET','secret');get_settings.cache_clear()
    app=FastAPI();app.add_middleware(InternalServiceAuthMiddleware)
    @app.get('/internal/v1/ping')
    def ping():return {'ok':True}
    client=TestClient(app)
    r=client.get('/internal/v1/ping',headers={'x-internal-service':'verideploy-gateway','x-tenant-id':'tenant-a','x-correlation-id':'corr-a'})
    assert r.status_code==401 and r.json()['error']['code']=='INTERNAL_SERVICE_SIGNATURE_REQUIRED'
    ts=str(int(time.time()));path='/internal/v1/ping';sig=sign_internal_request(secret='secret',method='GET',path_with_query=path,tenant='tenant-a',correlation='corr-a',timestamp=ts)
    r=client.get(path,headers={'x-internal-service':'verideploy-gateway','x-tenant-id':'tenant-a','x-correlation-id':'corr-a','x-service-auth-timestamp':ts,'x-service-auth-signature':sig})
    assert r.status_code==200
    get_settings.cache_clear()

def test_tampered_signature_fails(monkeypatch):
    monkeypatch.setenv('APP_ENV','test');monkeypatch.setenv('INTERNAL_SERVICE_AUTH_REQUIRED','true');monkeypatch.setenv('INTERNAL_SERVICE_AUTH_SECRET','secret');get_settings.cache_clear()
    app=FastAPI();app.add_middleware(InternalServiceAuthMiddleware)
    @app.post('/internal/v1/ping')
    async def ping():return {'ok':True}
    ts=str(int(time.time()));sig=sign_internal_request(secret='secret',method='POST',path_with_query='/internal/v1/ping',tenant='tenant-a',correlation='corr-a',timestamp=ts,body='{}')
    r=TestClient(app).post('/internal/v1/ping',content='{"tampered":true}',headers={'content-type':'application/json','x-internal-service':'verideploy-gateway','x-tenant-id':'tenant-a','x-correlation-id':'corr-a','x-service-auth-timestamp':ts,'x-service-auth-signature':sig})
    assert r.status_code==401
    get_settings.cache_clear()

def test_production_middleware_forces_service_auth_even_without_toggle():
    source=(ROOT/'services/ai/middleware/internal_service_auth.py').read_text()
    assert 'settings.app_env in {"staging","production"}' in source
    assert 'settings.internal_service_auth_secret' in source and 'settings.app_secret_key' in source

def test_browser_has_no_python_route_and_ai_service_is_not_host_published():
    web='\n'.join(p.read_text(errors='ignore') for p in (ROOT/'apps/web').rglob('*') if p.suffix in {'.ts','.tsx','.js','.jsx'})
    assert '/internal/v1/' not in web
    assert 'AI_SERVICE_BASE_URL' not in web and 'ai-service:8000' not in web
    compose=(ROOT/'docker-compose.yml').read_text()
    ai_block=compose.split('  ai-service:',1)[1].split('\n  release-risk-worker:',1)[0]
    assert 'ports:' not in ai_block

def test_gateway_private_calls_are_centralized_and_signed():
    files=list((ROOT/'apps/gateway/src').rglob('*.ts'))
    offenders=[]
    for p in files:
        if p.name=='private-ai.client.ts':continue
        if 'fetch(' in p.read_text(errors='ignore'):offenders.append(str(p.relative_to(ROOT)))
    assert offenders==[]
    client=(ROOT/'apps/gateway/src/boundary/private-ai.client.ts').read_text()
    for token in ['x-service-auth-timestamp','x-service-auth-signature','x-tenant-id','x-correlation-id','createHmac','/internal/v1/']:
        assert token in client
    assert 'retry:false' in (ROOT/'apps/gateway/src/approvals/approvals.service.ts').read_text()

def test_consistent_public_error_envelope_and_boundary_module():
    f=(ROOT/'apps/gateway/src/boundary/api-exception.filter.ts').read_text();main=(ROOT/'apps/gateway/src/main.ts').read_text();app=(ROOT/'apps/gateway/src/app.module.ts').read_text()
    for token in ['code','message','status','correlation_id','details']:assert token in f
    assert 'useGlobalFilters(new ApiExceptionFilter())' in main
    assert 'BoundaryModule' in app

def test_cursor_pagination_contract_is_opaque_and_bounded():
    py=(ROOT/'services/ai/routes/investigations.py').read_text();ts=(ROOT/'apps/gateway/src/investigations/investigations.controller.ts').read_text()
    for token in ['_decode_cursor','_encode_cursor','next_cursor','limit: int = Query(default=25, ge=1, le=100)']:assert token in py
    assert '@Get("page")' in ts

def test_upload_handoff_is_object_store_not_python_and_is_idempotent():
    ctl=(ROOT/'apps/gateway/src/ingestion/ingestion.controller.ts').read_text();svc=(ROOT/'apps/gateway/src/ingestion/ingestion.service.ts').read_text();storage=(ROOT/'apps/gateway/src/ingestion/object-storage.ts').read_text()
    assert '@Post("uploads/handoff")' in ctl and '@Post("uploads/:jobId/complete")' in ctl
    assert 'stableUuid(tenantId,idempotencyKey)' in svc
    assert 'createUploadHandoff' in storage and 'HeadObjectCommand' in storage and 'getSignedUrl' in storage
    assert 'stored object sha256 metadata mismatch' in storage

def test_openapi_public_contract_has_paths_and_no_internal_paths():
    import yaml
    d=yaml.safe_load((ROOT/'contracts/openapi/gateway.yaml').read_text())
    assert tuple(map(int,d['info']['version'].split('.'))) >= (0,43,0)
    assert '/investigations/page' in d['paths'] and '/ingestion/uploads/handoff' in d['paths'] and '/ingestion/uploads/{jobId}/complete' in d['paths']
    assert not any('/internal/' in p for p in d['paths'])

def test_version_and_env_contract():
    version=(ROOT/'src/verideploy/__init__.py').read_text().strip().split('\"')[1]
    assert tuple(map(int,version.split('.'))) >= (0,43,0)
    env=(ROOT/'.env.example').read_text()
    for k in ['INTERNAL_SERVICE_AUTH_REQUIRED','INTERNAL_SERVICE_AUTH_SECRET','INTERNAL_SERVICE_AUTH_MAX_SKEW_SECONDS','AI_SERVICE_TIMEOUT_MS','AI_SERVICE_MAX_ATTEMPTS']:assert k in env
