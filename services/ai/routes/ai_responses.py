from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from services.ai.ai_gateway import get_ai_gateway
from verideploy.llm.contracts import AIRequest, AIResult
from verideploy.llm.gateway import AIGateway

router = APIRouter(prefix="/internal/v1/ai/responses", tags=["ai-responses-internal"])


def _authorize(service_name: str) -> None:
    if service_name != "verideploy-gateway":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


def _tenant_scope(header_tenant: UUID | None, request_tenant: UUID) -> None:
    if header_tenant is not None and header_tenant != request_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant scope mismatch")


@router.post("", response_model=AIResult)
async def execute_response(
    payload: AIRequest,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    gateway: AIGateway = Depends(get_ai_gateway),
) -> AIResult:
    _authorize(x_internal_service)
    _tenant_scope(x_tenant_id, payload.tenant_id)
    return await gateway.execute(payload)


@router.post("/stream")
async def stream_response(
    payload: AIRequest,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    gateway: AIGateway = Depends(get_ai_gateway),
) -> StreamingResponse:
    _authorize(x_internal_service)
    _tenant_scope(x_tenant_id, payload.tenant_id)

    async def event_source():
        async for event in gateway.stream(payload):
            yield f"event: {event.type.value}\ndata: {event.model_dump_json()}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/{provider_response_id}", response_model=AIResult)
async def get_persisted_response(
    provider_response_id: str,
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
    gateway: AIGateway = Depends(get_ai_gateway),
) -> AIResult:
    _authorize(x_internal_service)
    if x_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="x-tenant-id is required")
    result = await gateway.get_persisted_response(
        tenant_id=x_tenant_id, provider_response_id=provider_response_id
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="response not found")
    return result


@router.post("/{provider_response_id}/cancel")
async def cancel_response(
    provider_response_id: str,
    x_internal_service: str = Header(default=""),
    gateway: AIGateway = Depends(get_ai_gateway),
) -> dict[str, object]:
    _authorize(x_internal_service)
    cancelled = await gateway.cancel(provider_response_id)
    return {"provider_response_id": provider_response_id, "cancelled": cancelled}
