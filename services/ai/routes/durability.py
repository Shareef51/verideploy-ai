from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from services.ai.durability import WorkflowDurabilityOperations, get_workflow_durability_operations
from verideploy.graphs.durability import RecoveryCandidate, ReplayResult, DurabilityEvent

router=APIRouter(prefix='/internal/v1/workflows/durability',tags=['workflow-durability-internal'])
TRUSTED={'verideploy-gateway','verideploy-investigation-worker'}

def _auth(service:str,tenant:UUID|None)->UUID:
    if service not in TRUSTED: raise HTTPException(status_code=401,detail='trusted service identity required')
    if tenant is None: raise HTTPException(status_code=400,detail='tenant header required')
    return tenant

class CancelRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    actor_id:str=Field(min_length=1,max_length=256)
    reason:str=Field(min_length=1,max_length=1000)

@router.get('/stuck',response_model=list[RecoveryCandidate])
def stuck(x_internal_service:str=Header(default=''),x_tenant_id:UUID|None=Header(default=None),ops:WorkflowDurabilityOperations=Depends(get_workflow_durability_operations)):
    return ops.stuck(tenant_id=_auth(x_internal_service,x_tenant_id))

@router.get('/{run_id}/events',response_model=list[DurabilityEvent])
def events(run_id:UUID,after_sequence:int=Query(default=0,ge=0),x_internal_service:str=Header(default=''),x_tenant_id:UUID|None=Header(default=None),ops:WorkflowDurabilityOperations=Depends(get_workflow_durability_operations)):
    tenant=_auth(x_internal_service,x_tenant_id); return ops.durability.events(tenant_id=tenant,run_id=run_id,after_sequence=after_sequence)

@router.get('/{run_id}/replay',response_model=ReplayResult)
def replay(run_id:UUID,from_sequence:int=Query(default=0,ge=0),x_internal_service:str=Header(default=''),x_tenant_id:UUID|None=Header(default=None),ops:WorkflowDurabilityOperations=Depends(get_workflow_durability_operations)):
    return ops.replay(tenant_id=_auth(x_internal_service,x_tenant_id),run_id=run_id,from_sequence=from_sequence)

@router.post('/{run_id}/cancel',status_code=204)
def cancel(run_id:UUID,payload:CancelRequest,x_internal_service:str=Header(default=''),x_tenant_id:UUID|None=Header(default=None),ops:WorkflowDurabilityOperations=Depends(get_workflow_durability_operations)):
    try: ops.cancel(tenant_id=_auth(x_internal_service,x_tenant_id),run_id=run_id,actor_id=payload.actor_id,reason=payload.reason)
    except KeyError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
