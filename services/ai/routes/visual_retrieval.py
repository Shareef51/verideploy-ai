from uuid import UUID
from fastapi import APIRouter,Depends,Header,HTTPException,status
from services.ai.visual_retrieval import get_visual_retrieval_service
from verideploy.rag.visual_retrieval.schemas import VisualSearchQuery,VisualSearchResult
from verideploy.rag.visual_retrieval.service import VisualDocumentService
from verideploy.rag.access.http import authorization_from_headers
from verideploy.rag.access.schemas import VISUAL_PERMISSION
router=APIRouter(prefix="/internal/v1/retrieval",tags=["visual-retrieval-internal"])
def _auth(s:str)->None:
    if s not in {"verideploy-gateway","verideploy-investigation-worker","verideploy-multimodal-worker"}: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="trusted service identity required")
@router.post("/visual",response_model=VisualSearchResult)
def visual_search(payload:VisualSearchQuery,x_internal_service:str=Header(default=""),x_tenant_id:UUID|None=Header(default=None),x_retrieval_permissions:str|None=Header(default=None),x_allowed_services:str|None=Header(default=None),x_allowed_environments:str|None=Header(default=None),x_allowed_teams:str|None=Header(default=None),x_allowed_document_kinds:str|None=Header(default=None),service:VisualDocumentService=Depends(get_visual_retrieval_service))->VisualSearchResult:
    _auth(x_internal_service)
    tenant=x_tenant_id or payload.tenant_id
    if tenant!=payload.tenant_id: raise HTTPException(status_code=403,detail="tenant scope mismatch")
    auth=authorization_from_headers(tenant_id=tenant,permissions=x_retrieval_permissions,allowed_services=x_allowed_services,allowed_environments=x_allowed_environments,allowed_teams=x_allowed_teams,allowed_document_kinds=x_allowed_document_kinds,default_permissions=frozenset({VISUAL_PERMISSION}))
    try:
        return service.search(payload,authorization=auth)
    except TypeError as exc:
        if "authorization" not in str(exc): raise
        return service.search(payload)
