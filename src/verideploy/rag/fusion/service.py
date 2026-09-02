from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from math import ceil
from uuid import UUID, uuid5, NAMESPACE_URL

from verideploy.rag.fusion.schemas import (
    CitedMultimodalAnswer,
    ContextBlock,
    EvidenceChannel,
    EvidenceCitation,
    EvidenceLocator,
    FusionTrace,
    MultimodalFusionRequest,
    MultimodalFusionResult,
    NormalizedEvidence,
    RuntimeEvidenceInput,
    make_citation_id,
)


class MultimodalEvidenceFusion:
    """Deterministic cross-channel evidence normalization and context assembly.

    This service never calls a model. It converts already-authorized retrieval/runtime
    outputs into one auditable evidence contract and enforces context/image budgets.
    """

    def __init__(self, default_budgets=None) -> None:
        from verideploy.rag.fusion.schemas import FusionBudgets
        self.default_budgets = default_budgets or FusionBudgets()

    def fuse(self, request: MultimodalFusionRequest) -> MultimodalFusionResult:
        candidates = self._normalize(request)
        candidate_counts = self._count_channels(candidates)
        unique, duplicate_count = self._deduplicate(candidates)
        selected, token_drops, image_drops = self._budget_select(unique, request)

        citations = [
            EvidenceCitation(
                citation_id=make_citation_id(item.evidence_id),
                evidence_id=item.evidence_id,
                channel=item.channel,
                title=item.title,
                locator=item.locator,
            )
            for item in selected
        ]
        by_id = {citation.evidence_id: citation for citation in citations}
        context = [
            ContextBlock(
                citation_id=by_id[item.evidence_id].citation_id,
                channel=item.channel,
                title=item.title,
                content=item.content,
                estimated_tokens=item.estimated_tokens,
                image_ref=item.locator.image_ref if item.channel is EvidenceChannel.VISUAL else None,
            )
            for item in selected
        ]
        selected_counts = self._count_channels(selected)
        contributing = [channel for channel in EvidenceChannel if selected_counts[channel] > 0]
        return MultimodalFusionResult(
            evidence=selected,
            context=context,
            citations=citations,
            contributing_channels=contributing,
            trace=FusionTrace(
                tenant_id=request.tenant_id,
                query=request.query,
                candidates_by_channel=candidate_counts,
                selected_by_channel=selected_counts,
                duplicate_count=duplicate_count,
                dropped_for_token_budget=token_drops,
                dropped_for_image_budget=image_drops,
                token_budget=(request.budgets or self.default_budgets).max_context_tokens,
                tokens_used=sum(item.estimated_tokens for item in selected),
                image_budget=(request.budgets or self.default_budgets).max_images,
                images_used=sum(item.image_cost for item in selected),
                selected_evidence_ids=[item.evidence_id for item in selected],
            ),
        )

    def validate_cited_answer(
        self, result: MultimodalFusionResult, answer: CitedMultimodalAnswer
    ) -> CitedMultimodalAnswer:
        """Require citation existence and coverage of every contributing channel."""
        citation_map = {item.citation_id: item for item in result.citations}
        used_ids = {citation_id for statement in answer.statements for citation_id in statement.citation_ids}
        unknown = sorted(used_ids - set(citation_map))
        if unknown:
            raise ValueError(f"answer references unknown citation IDs: {', '.join(unknown)}")
        used_channels = {citation_map[citation_id].channel for citation_id in used_ids}
        missing = [channel.value for channel in result.contributing_channels if channel not in used_channels]
        if missing:
            raise ValueError(f"answer must cite every contributing channel: {', '.join(missing)}")
        return answer

    def _normalize(self, request: MultimodalFusionRequest) -> list[NormalizedEvidence]:
        result: list[NormalizedEvidence] = []
        if request.text_result is not None:
            max_score = max((hit.fused_score for hit in request.text_result.hits), default=1.0)
            for hit in request.text_result.hits:
                content = hit.content.strip()
                content_hash = self._hash(content)
                evidence_id = uuid5(NAMESPACE_URL, f"{request.tenant_id}:text:{hit.chunk_id}:{content_hash}")
                relevance = min(1.0, hit.fused_score / max_score) if max_score > 0 else 0.0
                result.append(
                    NormalizedEvidence(
                        evidence_id=evidence_id,
                        tenant_id=request.tenant_id,
                        channel=EvidenceChannel.TEXT,
                        source_system="hybrid_retrieval",
                        source_id=str(hit.chunk_id),
                        source_key=hit.source_key,
                        title=hit.title,
                        content=content,
                        content_hash=content_hash,
                        relevance_score=relevance,
                        source_confidence=1.0,
                        fusion_score=self._fusion_score(relevance, 1.0),
                        locator=EvidenceLocator(document_id=hit.document_id, chunk_id=hit.chunk_id),
                        estimated_tokens=self._estimate_tokens(content),
                        provenance={"hybrid_rank": hit.rank, "fused_score": hit.fused_score},
                    )
                )

        if request.visual_result is not None:
            scores = [hit.score for hit in request.visual_result.hits]
            lo, hi = (min(scores), max(scores)) if scores else (0.0, 0.0)
            for hit in request.visual_result.hits:
                relevance = 1.0 if hi == lo and scores else ((hit.score - lo) / (hi - lo) if hi > lo else 0.0)
                content = f"Visual page {hit.page_number} from document {hit.document_id}; inspect image reference for visual evidence."
                evidence_id = uuid5(NAMESPACE_URL, f"{request.tenant_id}:visual:{hit.page_id}:{hit.image_sha256}")
                result.append(
                    NormalizedEvidence(
                        evidence_id=evidence_id,
                        tenant_id=request.tenant_id,
                        channel=EvidenceChannel.VISUAL,
                        source_system="visual_retrieval",
                        source_id=str(hit.page_id),
                        source_key=f"visual:{hit.document_id}:{hit.page_number}",
                        title=f"Visual page {hit.page_number}",
                        content=content,
                        content_hash=hit.image_sha256,
                        relevance_score=relevance,
                        source_confidence=0.95,
                        fusion_score=self._fusion_score(relevance, 0.95),
                        locator=EvidenceLocator(
                            document_id=hit.document_id,
                            page_id=hit.page_id,
                            page_number=hit.page_number,
                            image_ref=hit.image_path,
                        ),
                        estimated_tokens=self._estimate_tokens(content),
                        image_cost=1,
                        provenance={
                            "backend": hit.backend.value,
                            "model_name": hit.model_name,
                            "visual_score": hit.score,
                            "image_sha256": hit.image_sha256,
                        },
                    )
                )

        for item in request.runtime_evidence:
            result.append(self._runtime_to_evidence(item))
        return result

    def _runtime_to_evidence(self, item: RuntimeEvidenceInput) -> NormalizedEvidence:
        content = item.content.strip()
        content_hash = self._hash(content)
        return NormalizedEvidence(
            evidence_id=item.evidence_id,
            tenant_id=item.tenant_id,
            channel=EvidenceChannel.RUNTIME,
            source_system=item.source_system,
            source_id=item.source_id,
            source_key=f"runtime:{item.source_system}:{item.source_id}",
            title=item.title,
            content=content,
            content_hash=content_hash,
            relevance_score=item.relevance_score,
            source_confidence=item.source_confidence,
            fusion_score=self._fusion_score(item.relevance_score, item.source_confidence),
            locator=EvidenceLocator(timestamp=item.observed_at),
            estimated_tokens=self._estimate_tokens(content),
            provenance={
                "kind": item.kind.value,
                "service": item.service,
                "environment": item.environment,
            },
        )

    @staticmethod
    def _fusion_score(relevance: float, confidence: float) -> float:
        # Explicit, deterministic feature fusion. The LLM does not author this score.
        return round(max(0.0, min(1.0, 0.75 * relevance + 0.25 * confidence)), 8)

    @staticmethod
    def _hash(content: str) -> str:
        return sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _estimate_tokens(content: str) -> int:
        # Conservative provider-neutral budget approximation; actual model usage is
        # still authoritative later. Never counts image bytes as text.
        return max(1, ceil(len(content) / 4)) if content else 0

    @staticmethod
    def _count_channels(items: list[NormalizedEvidence]) -> dict[EvidenceChannel, int]:
        counts: dict[EvidenceChannel, int] = {channel: 0 for channel in EvidenceChannel}
        for item in items:
            counts[item.channel] += 1
        return counts

    def _deduplicate(self, items: list[NormalizedEvidence]) -> tuple[list[NormalizedEvidence], int]:
        # Prefer the strongest instance for identical content. Source identity is also
        # respected so retriever duplication cannot create duplicate citations.
        by_identity: dict[str, NormalizedEvidence] = {}
        duplicates = 0
        ordered = sorted(items, key=lambda item: (-item.fusion_score, item.channel.value, str(item.evidence_id)))
        for item in ordered:
            identity = f"hash:{item.content_hash}"
            source_identity = f"source:{item.source_system}:{item.source_id}"
            existing_key = identity if identity in by_identity else source_identity if source_identity in by_identity else None
            if existing_key is not None:
                duplicates += 1
                existing = by_identity[existing_key]
                if item.fusion_score > existing.fusion_score:
                    by_identity[existing_key] = item
                continue
            by_identity[identity] = item
            by_identity[source_identity] = item
        unique_by_id = {item.evidence_id: item for item in by_identity.values()}
        return sorted(unique_by_id.values(), key=lambda item: (-item.fusion_score, item.channel.value, str(item.evidence_id))), duplicates

    def _budget_select(
        self, items: list[NormalizedEvidence], request: MultimodalFusionRequest
    ) -> tuple[list[NormalizedEvidence], int, int]:
        budgets = request.budgets or self.default_budgets
        per_channel: dict[EvidenceChannel, list[NormalizedEvidence]] = defaultdict(list)
        for item in items:
            per_channel[item.channel].append(item)

        # Fair round-robin across available channels, strongest item first in each channel.
        selected: list[NormalizedEvidence] = []
        channel_counts = {channel: 0 for channel in EvidenceChannel}
        tokens = 0
        images = 0
        token_drops = 0
        image_drops = 0
        cursors = {channel: 0 for channel in EvidenceChannel}
        channels = [channel for channel in EvidenceChannel if per_channel[channel]]

        while len(selected) < budgets.max_total_evidence:
            progressed = False
            for channel in channels:
                if channel_counts[channel] >= budgets.max_per_channel:
                    continue
                index = cursors[channel]
                if index >= len(per_channel[channel]):
                    continue
                item = per_channel[channel][index]
                cursors[channel] += 1
                progressed = True
                if item.image_cost and images + item.image_cost > budgets.max_images:
                    image_drops += 1
                    continue
                if tokens + item.estimated_tokens > budgets.max_context_tokens:
                    token_drops += 1
                    continue
                selected.append(item)
                channel_counts[channel] += 1
                tokens += item.estimated_tokens
                images += item.image_cost
                if len(selected) >= budgets.max_total_evidence:
                    break
            if not progressed or all(cursors[channel] >= len(per_channel[channel]) for channel in channels):
                break

        return selected, token_drops, image_drops
