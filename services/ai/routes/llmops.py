from uuid import UUID
from fastapi import APIRouter,Depends,Header,HTTPException
from services.ai.llmops import get_llmops_service
from verideploy.llmops.schemas import CorrelationTrace
router=APIRouter(prefix='/internal/v1/llmops',tags=['llmops-internal'])
def _auth(s):
    if s not in {'verideploy-gateway','verideploy-investigation-worker'}: raise HTTPException(status_code=401,detail='trusted service identity required')
@router.get('/correlations/{correlation_id}',response_model=CorrelationTrace)
def trace(correlation_id:str,x_tenant_id:UUID=Header(),x_internal_service:str=Header(default=''),service=Depends(get_llmops_service)):
    _auth(x_internal_service); return service.trace(tenant_id=x_tenant_id,correlation_id=correlation_id)
