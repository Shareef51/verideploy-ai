from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status

from verideploy.config import get_settings
from verideploy.llm.factory import load_pricing_catalog

router = APIRouter(prefix="/internal/v1/ai", tags=["ai-internal"])


def _authorize(service_name: str) -> None:
    if service_name != "verideploy-gateway":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")


@router.get("/status")
async def ai_status(
    x_internal_service: str = Header(default=""),
    x_tenant_id: UUID | None = Header(default=None),
) -> dict[str, object]:
    _authorize(x_internal_service)
    settings = get_settings()
    try:
        catalog = load_pricing_catalog(settings)
        catalog_status: dict[str, object] = {
            "loaded": catalog is not None,
            "version": catalog.catalog_version if catalog else None,
            "effective_at": catalog.effective_at.isoformat() if catalog else None,
            "priced_models": len(catalog.models) if catalog else 0,
        }
    except ValueError as exc:
        catalog_status = {"loaded": False, "error": str(exc)}
    return {
        "provider": settings.ai_provider,
        "control_backend": settings.ai_control_backend,
        "timeout_seconds": settings.ai_timeout_seconds,
        "max_attempts": settings.ai_max_attempts,
        "requests_per_minute": settings.ai_requests_per_minute,
        "budget_configured": settings.ai_monthly_budget_usd > 0,
        "openai_key_configured": settings.openai_api_key is not None,
        "tenant_scope_received": x_tenant_id is not None,
        "model_roles": {
            "fast": settings.openai_fast_model,
            "standard": settings.openai_standard_model,
            "reasoning": settings.openai_reasoning_model,
        },
        "fallback_counts": {
            "fast": len([v for v in settings.openai_fast_fallback_models.split(",") if v.strip()]),
            "standard": len([v for v in settings.openai_standard_fallback_models.split(",") if v.strip()]),
            "reasoning": len([v for v in settings.openai_reasoning_fallback_models.split(",") if v.strip()]),
        },
        "concurrency_limits": {
            "fast": settings.ai_fast_concurrency,
            "standard": settings.ai_standard_concurrency,
            "reasoning": settings.ai_reasoning_concurrency,
        },
        "pricing_catalog": catalog_status,
    }
