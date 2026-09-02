from __future__ import annotations

from typing import Protocol

from .schemas import ExternalEvidence

EXTERNAL_SEARCH_PERMISSION = "retrieval.external.read"


class ExternalSearchProvider(Protocol):
    async def search(self, *, query: str, max_results: int) -> list[ExternalEvidence]: ...
