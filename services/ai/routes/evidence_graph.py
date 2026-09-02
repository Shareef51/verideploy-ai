from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from services.ai.evidence_graph import get_evidence_graph_service
from verideploy.evidence_graph.repository import GraphConflictError, GraphNotFoundError, GraphTenantViolation
from verideploy.evidence_graph.schemas import GraphEdge, GraphEdgeCreate, GraphEntity, GraphEntityCreate, GraphPath, GraphSnapshot
from verideploy.evidence_graph.service import EvidenceGraphService

router=APIRouter(prefix="/internal/v1/evidence-graph",tags=["evidence-graph-internal"])

def _trusted(service:str)->None:
    if service not in {"verideploy-gateway","verideploy-investigation-worker"}: raise HTTPException(status_code=401,detail="trusted service identity required")
def _tenant(header:UUID,body:UUID)->None:
    if header!=body: raise HTTPException(status_code=403,detail="tenant mismatch")
def _translate(exc:Exception)->HTTPException:
    if isinstance(exc,GraphNotFoundError): return HTTPException(status_code=404,detail=str(exc))
    if isinstance(exc,GraphTenantViolation): return HTTPException(status_code=403,detail=str(exc))
    if isinstance(exc,GraphConflictError): return HTTPException(status_code=409,detail=str(exc))
    raise exc

@router.post("/entities",response_model=GraphEntity,status_code=status.HTTP_201_CREATED)
def put_entity(payload:GraphEntityCreate,x_internal_service:str=Header(default=""),x_tenant_id:UUID=Header(...),service:EvidenceGraphService=Depends(get_evidence_graph_service))->GraphEntity:
    _trusted(x_internal_service);_tenant(x_tenant_id,payload.tenant_id)
    try:return service.put_entity(payload)
    except (GraphNotFoundError,GraphTenantViolation,GraphConflictError) as exc: raise _translate(exc)

@router.post("/edges",response_model=GraphEdge,status_code=status.HTTP_201_CREATED)
def put_edge(payload:GraphEdgeCreate,x_internal_service:str=Header(default=""),x_tenant_id:UUID=Header(...),service:EvidenceGraphService=Depends(get_evidence_graph_service))->GraphEdge:
    _trusted(x_internal_service);_tenant(x_tenant_id,payload.tenant_id)
    try:return service.put_edge(payload)
    except (GraphNotFoundError,GraphTenantViolation,GraphConflictError) as exc: raise _translate(exc)

@router.get("/path",response_model=GraphPath)
def path(source_entity_id:UUID=Query(...),target_entity_id:UUID=Query(...),max_depth:int=Query(default=6,ge=1,le=12),x_internal_service:str=Header(default=""),x_tenant_id:UUID=Header(...),service:EvidenceGraphService=Depends(get_evidence_graph_service))->GraphPath:
    _trusted(x_internal_service)
    try:return service.path(tenant_id=x_tenant_id,source_entity_id=source_entity_id,target_entity_id=target_entity_id,max_depth=max_depth)
    except (GraphNotFoundError,GraphConflictError) as exc: raise _translate(exc)

@router.get("/snapshot",response_model=GraphSnapshot)
def snapshot(x_internal_service:str=Header(default=""),x_tenant_id:UUID=Header(...),service:EvidenceGraphService=Depends(get_evidence_graph_service))->GraphSnapshot:
    _trusted(x_internal_service);return service.snapshot(tenant_id=x_tenant_id)
