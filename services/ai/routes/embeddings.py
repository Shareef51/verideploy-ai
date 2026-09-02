from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from services.ai.embedding_pipeline import get_embedding_pipeline
from verideploy.rag.embeddings.pipeline import EmbeddingPipeline
from verideploy.rag.embeddings.schemas import EmbeddingBatchResult, EmbeddingRequest

router = APIRouter(prefix="/internal/v1/embeddings", tags=["embeddings-internal"])


def _authorize(service_name: str) -> None:
    if service_name not in {"verideploy-gateway", "verideploy-embedding-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


@router.post("", response_model=EmbeddingBatchResult)
async def create_embeddings(
    payload: EmbeddingRequest,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    pipeline: EmbeddingPipeline = Depends(get_embedding_pipeline),
) -> EmbeddingBatchResult:
    _authorize(x_internal_service)
    if x_tenant_id is not None and x_tenant_id != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope mismatch")
    return await pipeline.embed(payload)
