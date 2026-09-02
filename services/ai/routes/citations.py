from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter,Depends,Header,HTTPException,status
from services.ai.citations import get_citation_service
from verideploy.rag.access.http import authorization_from_headers
from verideploy.rag.access.schemas import PREVIEW_PERMISSION,READ_PERMISSION
from verideploy.rag.citations.schemas import CitationBuildRequest,CitationBundle,CitationPreview,CitationRecord,ClaimCitationLink
from verideploy.rag.citations.service import CitationService

router=APIRouter(prefix="/internal/v1/citations",tags=["citations-internal"])
TRUSTED={"verideploy-gateway","verideploy-investigation-worker"}
def _auth(service:str):
    if service not in TRUSTED:raise HTTPException(status_code=401,detail="trusted service identity required")

@router.post("/from-verification",response_model=CitationBundle)
def build(payload:CitationBuildRequest,x_internal_service:str=Header(default=""),x_tenant_id:UUID|None=Header(default=None),service:CitationService=Depends(get_citation_service)):
    _auth(x_internal_service); tenant=x_tenant_id or payload.tenant_id
    if tenant!=payload.tenant_id:raise HTTPException(status_code=403,detail="tenant scope mismatch")
    try:return service.build_from_verification(payload)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get("/{citation_id}",response_model=CitationRecord)
def get_citation(citation_id:UUID,x_internal_service:str=Header(default=""),x_tenant_id:UUID|None=Header(default=None),service:CitationService=Depends(get_citation_service)):
    _auth(x_internal_service)
    if x_tenant_id is None:raise HTTPException(status_code=400,detail="tenant header required")
    result=service.get_citation(tenant_id=x_tenant_id,citation_id=citation_id)
    if result is None:raise HTTPException(status_code=404,detail="citation not found")
    return result

@router.get("/verifications/{verification_id}/claims/{claim_id}",response_model=list[ClaimCitationLink])
def claim_links(verification_id:UUID,claim_id:str,x_internal_service:str=Header(default=""),x_tenant_id:UUID|None=Header(default=None),service:CitationService=Depends(get_citation_service)):
    _auth(x_internal_service)
    if x_tenant_id is None:raise HTTPException(status_code=400,detail="tenant header required")
    return service.claim_links(tenant_id=x_tenant_id,verification_id=verification_id,claim_id=claim_id)

@router.get("/{citation_id}/preview",response_model=CitationPreview)
def preview(citation_id:UUID,x_internal_service:str=Header(default=""),x_tenant_id:UUID|None=Header(default=None),x_retrieval_permissions:str|None=Header(default=None),x_allowed_services:str|None=Header(default=None),x_allowed_environments:str|None=Header(default=None),x_allowed_teams:str|None=Header(default=None),x_allowed_document_kinds:str|None=Header(default=None),service:CitationService=Depends(get_citation_service)):
    _auth(x_internal_service)
    if x_tenant_id is None:raise HTTPException(status_code=400,detail="tenant header required")
    authorization=authorization_from_headers(tenant_id=x_tenant_id,permissions=x_retrieval_permissions,allowed_services=x_allowed_services,allowed_environments=x_allowed_environments,allowed_teams=x_allowed_teams,allowed_document_kinds=x_allowed_document_kinds,default_permissions=frozenset({READ_PERMISSION,PREVIEW_PERMISSION}))
    result=service.preview(tenant_id=x_tenant_id,citation_id=citation_id,authorization=authorization)
    if result is None:raise HTTPException(status_code=404,detail="citation preview not accessible")
    return result
