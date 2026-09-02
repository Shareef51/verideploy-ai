from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from services.ai.retrieval import get_hybrid_retriever, get_source_preview_repository
from verideploy.rag.retrieval.schemas import HybridRetrievalResult, RetrievalQuery
from verideploy.rag.retrieval.service import HybridRetriever
from verideploy.rag.access.http import authorization_from_headers
from verideploy.rag.access.schemas import RequestedMetadataFilters, PREVIEW_PERMISSION
from verideploy.rag.access.source_preview import PostgresSourcePreviewRepository, SourcePreview
from verideploy.rag.access.schemas import build_effective_scope

router = APIRouter(prefix="/internal/v1/retrieval", tags=["retrieval-internal"])


def _authorize(service_name: str) -> None:
    if service_name not in {"verideploy-gateway", "verideploy-investigation-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


@router.post("/hybrid", response_model=HybridRetrievalResult)
async def hybrid_retrieval(
    payload: RetrievalQuery,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    x_retrieval_permissions: str | None = Header(default=None),
    x_allowed_services: str | None = Header(default=None),
    x_allowed_environments: str | None = Header(default=None),
    x_allowed_teams: str | None = Header(default=None),
    x_allowed_document_kinds: str | None = Header(default=None),
    retriever: HybridRetriever = Depends(get_hybrid_retriever),
) -> HybridRetrievalResult:
    _authorize(x_internal_service)
    tenant=x_tenant_id or payload.tenant_id
    if tenant != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope mismatch")
    auth=authorization_from_headers(tenant_id=tenant,permissions=x_retrieval_permissions,allowed_services=x_allowed_services,allowed_environments=x_allowed_environments,allowed_teams=x_allowed_teams,allowed_document_kinds=x_allowed_document_kinds)
    try:
        return await retriever.retrieve(payload,authorization=auth)
    except TypeError as exc:
        if "authorization" not in str(exc): raise
        return await retriever.retrieve(payload)

from services.ai.retrieval_pipeline import get_retrieval_pipeline
from services.ai.llmops import get_llmops_service
from services.ai.langsmith import get_langsmith_observer
from verideploy.llmops.schemas import LLMOpsEvent, LLMOpsKind
from verideploy.rag.orchestration.schemas import RetrievalPipelineRequest, RetrievalPipelineResult, RetrievalPipelineTrace
from verideploy.rag.orchestration.service import RetrievalPipeline


@router.post("/orchestrated", response_model=RetrievalPipelineResult)
async def orchestrated_retrieval(
    payload: RetrievalPipelineRequest,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    x_retrieval_permissions: str | None = Header(default=None),
    x_allowed_services: str | None = Header(default=None),
    x_allowed_environments: str | None = Header(default=None),
    x_allowed_teams: str | None = Header(default=None),
    x_allowed_document_kinds: str | None = Header(default=None),
    x_correlation_id: str | None = Header(default=None),
    pipeline: RetrievalPipeline = Depends(get_retrieval_pipeline),
    llmops=Depends(get_llmops_service),
    langsmith=Depends(get_langsmith_observer),
) -> RetrievalPipelineResult:
    _authorize(x_internal_service)
    tenant=x_tenant_id or payload.tenant_id
    if tenant != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope mismatch")
    auth=authorization_from_headers(tenant_id=tenant,permissions=x_retrieval_permissions,allowed_services=x_allowed_services,allowed_environments=x_allowed_environments,allowed_teams=x_allowed_teams,allowed_document_kinds=x_allowed_document_kinds)
    result=await pipeline.run(payload,authorization=auth)
    if x_correlation_id:
        confidence=max((c.rerank_score for c in result.candidates),default=None)
        llmops.record(LLMOpsEvent(tenant_id=tenant,correlation_id=x_correlation_id,retrieval_run_id=result.trace.run_id,kind=LLMOpsKind.RETRIEVAL,operation="rag.orchestrated",retrieval_count=len(result.candidates),confidence=confidence,payload={"pipeline_version":result.trace.pipeline_version,"selected_chunk_count":len(result.trace.selected_chunk_ids)}))
        langsmith.trace_fact(
            tenant_id=tenant, correlation_id=x_correlation_id,
            span_key=f"retrieval:{result.trace.run_id}", name="rag.orchestrated", run_type="retriever",
            inputs={"query_sha256": result.trace.input_sha256},
            outputs={"candidate_count": len(result.candidates), "selected_chunk_count": len(result.trace.selected_chunk_ids)},
            metadata={"pipeline_version": result.trace.pipeline_version, "confidence": confidence},
        )
    return result


@router.get("/source-preview/{document_id}", response_model=SourcePreview)
def source_preview(
    document_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    x_retrieval_permissions: str | None = Header(default=None),
    x_allowed_services: str | None = Header(default=None),
    x_allowed_environments: str | None = Header(default=None),
    x_allowed_teams: str | None = Header(default=None),
    x_allowed_document_kinds: str | None = Header(default=None),
    service: str | None = None, environment: str | None = None, team: str | None = None, severity: str | None = None,
    repository: PostgresSourcePreviewRepository = Depends(get_source_preview_repository),
) -> SourcePreview:
    _authorize(x_internal_service)
    if x_tenant_id is None: raise HTTPException(status_code=400,detail="tenant header required")
    auth=authorization_from_headers(tenant_id=x_tenant_id,permissions=x_retrieval_permissions,allowed_services=x_allowed_services,allowed_environments=x_allowed_environments,allowed_teams=x_allowed_teams,allowed_document_kinds=x_allowed_document_kinds,default_permissions=frozenset({PREVIEW_PERMISSION,"retrieval.read"}))
    requested=RequestedMetadataFilters(services=[service] if service else [],environments=[environment] if environment else [],teams=[team] if team else [],severities=[severity] if severity else [])
    scope=build_effective_scope(authorization=auth,requested=requested,required_permission=PREVIEW_PERMISSION)
    item=repository.preview(document_id=document_id,scope=scope)
    if item is None: raise HTTPException(status_code=404,detail="source preview not found")
    return item

@router.get("/traces/{run_id}", response_model=RetrievalPipelineTrace)
def retrieval_pipeline_trace(
    run_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    pipeline: RetrievalPipeline = Depends(get_retrieval_pipeline),
) -> RetrievalPipelineTrace:
    _authorize(x_internal_service)
    if x_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant header required")
    trace = pipeline.get_trace(tenant_id=x_tenant_id, run_id=run_id)
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="retrieval trace not found")
    return trace

from services.ai.self_corrective_rag import get_self_corrective_rag
from verideploy.rag.self_corrective.schemas import SelfCorrectiveRAGRequest, SelfCorrectiveRAGResult
from verideploy.rag.self_corrective.service import SelfCorrectiveRAG


@router.post("/self-corrective", response_model=SelfCorrectiveRAGResult)
async def self_corrective_retrieval(
    payload: SelfCorrectiveRAGRequest,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    x_retrieval_permissions: str | None = Header(default=None),
    x_allowed_services: str | None = Header(default=None),
    x_allowed_environments: str | None = Header(default=None),
    x_allowed_teams: str | None = Header(default=None),
    x_allowed_document_kinds: str | None = Header(default=None),
    controller: SelfCorrectiveRAG = Depends(get_self_corrective_rag),
) -> SelfCorrectiveRAGResult:
    _authorize(x_internal_service)
    tenant = x_tenant_id or payload.retrieval.tenant_id
    if tenant != payload.retrieval.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope mismatch")
    auth = authorization_from_headers(
        tenant_id=tenant, permissions=x_retrieval_permissions, allowed_services=x_allowed_services,
        allowed_environments=x_allowed_environments, allowed_teams=x_allowed_teams,
        allowed_document_kinds=x_allowed_document_kinds,
    )
    return await controller.run(payload, authorization=auth)


@router.get("/self-corrective/{run_id}", response_model=SelfCorrectiveRAGResult)
def self_corrective_trace(
    run_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    controller: SelfCorrectiveRAG = Depends(get_self_corrective_rag),
) -> SelfCorrectiveRAGResult:
    _authorize(x_internal_service)
    if x_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant header required")
    result = controller.get(tenant_id=x_tenant_id, run_id=run_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="self-corrective RAG run not found")
    return result


from services.ai.hallucination_protection import get_hallucination_protector
from verideploy.rag.hallucination.schemas import HallucinationProtectionRequest, HallucinationProtectionResult
from verideploy.rag.hallucination.service import HallucinationProtector


@router.post("/hallucination-protect", response_model=HallucinationProtectionResult)
def hallucination_protect(
    payload: HallucinationProtectionRequest,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    protector: HallucinationProtector = Depends(get_hallucination_protector),
) -> HallucinationProtectionResult:
    _authorize(x_internal_service)
    tenant = x_tenant_id or payload.tenant_id
    if tenant != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope mismatch")
    try:
        return protector.protect(payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/hallucination-protect/{verification_id}", response_model=HallucinationProtectionResult)
def hallucination_protection_trace(
    verification_id: UUID,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    protector: HallucinationProtector = Depends(get_hallucination_protector),
) -> HallucinationProtectionResult:
    _authorize(x_internal_service)
    if x_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant header required")
    result = protector.get(tenant_id=x_tenant_id, verification_id=verification_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="hallucination verification not found")
    return result
