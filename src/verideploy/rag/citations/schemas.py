from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CitationLocatorKind(StrEnum):
    TEXT = "text"
    PAGE = "page"
    TIMECODE = "timecode"
    CODE = "code"


class TextLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["text"] = "text"
    chunk_ordinal: int | None = Field(default=None, ge=0)


class PageLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["page"] = "page"
    page_number: int = Field(ge=1)
    bbox: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def valid_bbox(self) -> "PageLocator":
        if self.bbox is not None:
            x1, y1, x2, y2 = self.bbox
            if x2 < x1 or y2 < y1:
                raise ValueError("page bbox must satisfy x2>=x1 and y2>=y1")
        return self


class TimecodeLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["timecode"] = "timecode"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    speaker: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def ordered(self) -> "TimecodeLocator":
        if self.end_ms < self.start_ms:
            raise ValueError("timecode end_ms must be >= start_ms")
        return self


class CodeLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["code"] = "code"
    path: str = Field(min_length=1, max_length=1000)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{7,64}$")

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        value = value.strip().replace("\\", "/")
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("code locator path must be repository-relative")
        return value

    @model_validator(mode="after")
    def ordered(self) -> "CodeLocator":
        if self.end_line < self.start_line:
            raise ValueError("code end_line must be >= start_line")
        return self


CitationLocator = Annotated[Union[TextLocator, PageLocator, TimecodeLocator, CodeLocator], Field(discriminator="kind")]


class CitationBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    verification_id: UUID
    locators: dict[UUID, CitationLocator] = Field(default_factory=dict)


class CitationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    citation_id: UUID
    tenant_id: UUID
    document_id: UUID
    chunk_id: UUID
    source_key: str
    title: str
    source_version: str
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: CitationLocator
    required_permission: str = Field(min_length=1, max_length=160)
    service: str | None = None
    environment: str | None = None
    team: str | None = None
    document_kind: str | None = None
    deep_link: str


class ClaimCitationLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    verification_id: UUID
    claim_id: str
    citation_id: UUID
    entailment_score: float = Field(ge=0.0, le=1.0)
    entails_released_claim: bool
    claim_qualified: bool = False


class CitationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    verification_id: UUID
    citations: list[CitationRecord]
    mappings: list[ClaimCitationLink]
    final_claim_count: int = Field(ge=0)
    final_claims_cited: bool
    all_citations_entail: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class CitationPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation: CitationRecord
    excerpt: str = Field(max_length=4000)
    accessible: bool = True
