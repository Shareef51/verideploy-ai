from __future__ import annotations
from enum import StrEnum
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

class VisualBackend(StrEnum):
    COLPALI = "colpali"
    CPU_FALLBACK = "cpu_fallback"

class RenderedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    tenant_id: UUID
    page_number: int = Field(ge=1)
    image_path: str
    image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    native_text: str = ""

class VisualIndexRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index_id: UUID = Field(default_factory=uuid4)
    page_id: UUID
    tenant_id: UUID
    backend: VisualBackend
    model_name: str
    index_version: str
    embedding_ref: str | None = None
    feature_vector: list[float] | None = None

class VisualSearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    text: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=10, ge=1, le=100)
    document_id: UUID | None = None
    metadata_filters: "RequestedMetadataFilters | None" = None

class VisualSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: UUID
    document_id: UUID
    page_number: int
    score: float
    backend: VisualBackend
    model_name: str
    image_path: str
    image_sha256: str

class VisualSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: UUID = Field(default_factory=uuid4)
    backend: VisualBackend
    model_name: str
    hits: list[VisualSearchHit]

from verideploy.rag.access.schemas import RequestedMetadataFilters
VisualSearchQuery.model_rebuild()
