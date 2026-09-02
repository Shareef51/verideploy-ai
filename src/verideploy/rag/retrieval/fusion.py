from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from verideploy.rag.retrieval.schemas import (
    ChannelCandidate,
    HybridHit,
    RankingContribution,
    RetrievalChannel,
)


@dataclass(frozen=True)
class FusionConfig:
    rrf_k: int = 60
    max_per_source: int = 2
    keyword_weight: float = 0.5
    dense_weight: float = 0.5

    def __post_init__(self) -> None:
        if self.rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        if self.max_per_source <= 0:
            raise ValueError("max_per_source must be positive")
        if abs(self.keyword_weight + self.dense_weight - 1.0) > 1e-6:
            raise ValueError("fusion weights must sum to 1")


def normalize_scores(values: Iterable[float], *, higher_is_better: bool = True) -> list[float]:
    raw = [float(value) for value in values]
    if not raw:
        return []
    if not higher_is_better:
        raw = [-value for value in raw]
    low, high = min(raw), max(raw)
    if high == low:
        return [1.0 for _ in raw]
    return [(value - low) / (high - low) for value in raw]


def reciprocal_rank_fusion(
    keyword: list[ChannelCandidate],
    dense: list[ChannelCandidate],
    *,
    top_k: int,
    config: FusionConfig = FusionConfig(),
) -> list[HybridHit]:
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")

    candidates: dict[UUID, ChannelCandidate] = {}
    contributions: dict[UUID, list[RankingContribution]] = defaultdict(list)
    fused: dict[UUID, float] = defaultdict(float)

    for channel_hits in (keyword, dense):
        for hit in channel_hits:
            candidates.setdefault(hit.chunk_id, hit)
            weight = config.keyword_weight if hit.channel is RetrievalChannel.KEYWORD else config.dense_weight
            # Keep historical balanced-RRF score scale while changing channel influence.
            contribution = (2.0 * weight) / (config.rrf_k + hit.rank)
            fused[hit.chunk_id] += contribution
            contributions[hit.chunk_id].append(
                RankingContribution(
                    channel=hit.channel,
                    rank=hit.rank,
                    raw_score=hit.raw_score,
                    normalized_score=hit.normalized_score,
                    rrf_contribution=contribution,
                )
            )

    ordered_ids = sorted(
        fused,
        key=lambda chunk_id: (
            -fused[chunk_id],
            -max(item.normalized_score for item in contributions[chunk_id]),
            str(chunk_id),
        ),
    )

    selected: list[HybridHit] = []
    per_source: dict[str, int] = defaultdict(int)
    for chunk_id in ordered_ids:
        candidate = candidates[chunk_id]
        if per_source[candidate.source_key] >= config.max_per_source:
            continue
        per_source[candidate.source_key] += 1
        selected.append(
            HybridHit(
                chunk_id=candidate.chunk_id,
                document_id=candidate.document_id,
                source_key=candidate.source_key,
                title=candidate.title,
                content=candidate.content,
                rank=len(selected) + 1,
                fused_score=fused[chunk_id],
                contributions=sorted(contributions[chunk_id], key=lambda item: item.channel.value),
                document_kind=candidate.document_kind,
            )
        )
        if len(selected) >= top_k:
            break
    return selected
