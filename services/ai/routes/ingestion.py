from uuid import UUID
from fastapi import APIRouter, Header, HTTPException, Query, Request
from verideploy.multimodal.repository import SqlAlchemyIngestionRepository
from verideploy.multimodal.service import IngestionService

router=APIRouter(prefix="/internal/v1/ingestion", tags=["internal-ingestion"])

def _guard(service: str | None) -> None:
    if service != "verideploy-gateway": raise HTTPException(status_code=403, detail="internal service identity required")

def _svc(request: Request) -> IngestionService:
    settings=request.app.state.settings; return IngestionService(SqlAlchemyIngestionRepository(settings.database_url, create_schema=True))

@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, request: Request, x_internal_service: str | None=Header(default=None), x_tenant_id: UUID=Header()):
    _guard(x_internal_service); job=_svc(request).get(x_tenant_id,job_id)
    if job is None: raise HTTPException(status_code=404,detail="ingestion job not found")
    return job

@router.get("/jobs/{job_id}/events")
def get_events(job_id: UUID, request: Request, after_sequence: int=Query(default=0,ge=0), x_internal_service: str | None=Header(default=None), x_tenant_id: UUID=Header()):
    _guard(x_internal_service); svc=_svc(request)
    if svc.get(x_tenant_id,job_id) is None: raise HTTPException(status_code=404,detail="ingestion job not found")
    return svc.events(x_tenant_id,job_id,after_sequence=after_sequence)
