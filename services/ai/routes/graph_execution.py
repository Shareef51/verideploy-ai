from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from services.ai.graph_execution import GraphExecutionViewService, get_graph_execution_view_service
from verideploy.graphs.execution_projection import AgentExecutionProjection
from verideploy.graphs.runtime import GraphRuntimeEvent

router=APIRouter(prefix="/internal/v1/graph-runs",tags=["graph-execution-internal"])
def _auth(service:str):
    if service not in {"verideploy-gateway","verideploy-investigation-worker"}: raise HTTPException(status_code=401,detail="trusted service identity required")
@router.get("/{run_id}/execution-view",response_model=AgentExecutionProjection)
def execution_view(run_id:UUID,x_tenant_id:UUID=Header(),x_internal_service:str=Header(default=""),service:GraphExecutionViewService=Depends(get_graph_execution_view_service)):
    _auth(x_internal_service)
    try:return service.view(x_tenant_id,run_id)
    except KeyError as exc: raise HTTPException(status_code=404,detail="graph run not found") from exc
@router.get("/{run_id}/events",response_model=list[GraphRuntimeEvent])
def execution_events(run_id:UUID,x_tenant_id:UUID=Header(),x_internal_service:str=Header(default=""),after_sequence:int=Query(default=0,ge=0),service:GraphExecutionViewService=Depends(get_graph_execution_view_service)):
    _auth(x_internal_service)
    try:return service.events(x_tenant_id,run_id,after_sequence)
    except KeyError as exc: raise HTTPException(status_code=404,detail="graph run not found") from exc
