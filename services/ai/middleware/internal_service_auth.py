from __future__ import annotations
import hashlib, hmac, json, time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from verideploy.config import get_settings

TRUSTED_SERVICES={"verideploy-gateway","verideploy-investigation-worker","verideploy-multimodal-worker"}

def canonical(method:str,path_with_query:str,tenant:str,correlation:str,timestamp:str,body:str)->str:
    return "\n".join((method.upper(),path_with_query,tenant,correlation,timestamp,body))

def sign_internal_request(*,secret:str,method:str,path_with_query:str,tenant:str,correlation:str,timestamp:str,body:str="")->str:
    return hmac.new(secret.encode(),canonical(method,path_with_query,tenant,correlation,timestamp,body).encode(),hashlib.sha256).hexdigest()

class InternalServiceAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request:Request,call_next):
        if not request.url.path.startswith("/internal/v1/"):
            return await call_next(request)
        settings=get_settings(); service=request.headers.get("x-internal-service","")
        required=settings.internal_service_auth_required or settings.app_env in {"staging","production"}
        timestamp=request.headers.get("x-service-auth-timestamp"); signature=request.headers.get("x-service-auth-signature")
        if not timestamp or not signature:
            if required:return JSONResponse(status_code=401,content={"error":{"code":"INTERNAL_SERVICE_SIGNATURE_REQUIRED","message":"signed service authentication required"}})
            return await call_next(request)
        if service not in TRUSTED_SERVICES:
            return JSONResponse(status_code=401,content={"error":{"code":"INTERNAL_SERVICE_UNAUTHORIZED","message":"trusted service identity required"}})
        configured=json.loads(settings.internal_service_auth_secrets_json or "{}")
        secret=str(configured.get(service) or (settings.internal_service_auth_secret.get_secret_value() if settings.internal_service_auth_secret else settings.app_secret_key.get_secret_value()))
        try: ts=int(timestamp)
        except ValueError:return JSONResponse(status_code=401,content={"error":{"code":"INTERNAL_SERVICE_SIGNATURE_INVALID","message":"invalid service authentication timestamp"}})
        if abs(int(time.time())-ts)>settings.internal_service_auth_max_skew_seconds:
            return JSONResponse(status_code=401,content={"error":{"code":"INTERNAL_SERVICE_SIGNATURE_EXPIRED","message":"service authentication timestamp outside allowed skew"}})
        body_bytes=await request.body(); body=body_bytes.decode("utf-8") if body_bytes else ""
        path=request.url.path+(f"?{request.url.query}" if request.url.query else "")
        expected=sign_internal_request(secret=secret,method=request.method,path_with_query=path,tenant=request.headers.get("x-tenant-id",""),correlation=request.headers.get("x-correlation-id",""),timestamp=timestamp,body=body)
        if not hmac.compare_digest(expected,signature):
            return JSONResponse(status_code=401,content={"error":{"code":"INTERNAL_SERVICE_SIGNATURE_INVALID","message":"service authentication signature invalid"}})
        return await call_next(request)
