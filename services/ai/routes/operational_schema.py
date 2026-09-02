from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict
from verideploy.operational_schema.catalog import OPERATIONAL_SCHEMA_CATALOG, validate_schema_catalog

router = APIRouter(prefix="/internal/v1/schema", tags=["operational-schema-internal"])

class SchemaBindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept: str
    table: str
    schema_generation: int
    tenant_scoped: bool

class SchemaCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid: bool
    bindings: list[SchemaBindingResponse]


def _trusted(service: str) -> None:
    if service not in {"verideploy-gateway", "verideploy-investigation-worker"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="trusted service identity required")

@router.get("/catalog", response_model=SchemaCatalogResponse)
async def schema_catalog(x_internal_service: str = Header(default="")) -> SchemaCatalogResponse:
    _trusted(x_internal_service)
    result = validate_schema_catalog()
    return SchemaCatalogResponse(
        valid=bool(result["valid"]),
        bindings=[SchemaBindingResponse(**asdict(binding)) for binding in OPERATIONAL_SCHEMA_CATALOG.values()],
    )
