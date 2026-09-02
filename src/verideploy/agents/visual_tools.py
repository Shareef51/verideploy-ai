from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from verideploy.multimodal.image_intelligence import (
    ImageAnalysisType,
    ImageIntelligenceService,
    ImageProvenance,
    VisualAnalysisResult,
)
from verideploy.rag.visual_retrieval.schemas import VisualSearchHit, VisualSearchQuery, VisualSearchResult
from verideploy.rag.visual_retrieval.service import VisualDocumentService


class VisualSearchPort(Protocol):
    async def search(self, query: VisualSearchQuery) -> VisualSearchResult: ...


class VisualAnalysisPort(Protocol):
    async def analyze(
        self,
        *,
        tenant_id,
        correlation_id: str,
        hit: VisualSearchHit,
        analysis_type: ImageAnalysisType,
    ) -> tuple[ImageProvenance, VisualAnalysisResult]: ...


class VisualDocumentSearchTool:
    def __init__(self, service: VisualDocumentService) -> None:
        self.service = service

    async def search(self, query: VisualSearchQuery) -> VisualSearchResult:
        return self.service.search(query)


class StoredVisualAnalysisTool:
    """Analyze only images already admitted/indexed by visual document retrieval.

    The current visual index stores a filesystem image reference. This adapter verifies
    the exact indexed SHA-256 before passing bytes through the secure image
    preparation and provenance boundary. It never accepts an arbitrary remote URL.
    """

    def __init__(self, service: ImageIntelligenceService) -> None:
        self.service = service

    async def analyze(
        self,
        *,
        tenant_id,
        correlation_id: str,
        hit: VisualSearchHit,
        analysis_type: ImageAnalysisType,
    ) -> tuple[ImageProvenance, VisualAnalysisResult]:
        path = Path(hit.image_path)
        if not path.is_file():
            raise FileNotFoundError("indexed visual evidence image is unavailable")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != hit.image_sha256:
            raise ValueError("indexed visual evidence SHA-256 mismatch")
        return await self.service.analyze(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            source_object_ref=str(path),
            source_type="document_page",
            raw_bytes=raw,
            analysis_type=analysis_type,
            page_number=hit.page_number,
        )
