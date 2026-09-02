from __future__ import annotations

import math

from verideploy.evaluation.retrieval_metrics import (
    RankedHit,
    RetrievalObservation,
    compare_retrievers,
    confidence_interval_95,
    metadata_filter_correctness,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    score_observation,
)


def _hits(*ids: str) -> tuple[RankedHit, ...]:
    return tuple(RankedHit(source_id=value, metadata={"tenant_id": "t1", "authorized": True}) for value in ids)


def test_ranking_metric_formulas() -> None:
    hits = _hits("a", "x", "b", "z")
    relevant = {"a", "b"}
    assert recall_at_k(hits, relevant, 1) == 0.5
    assert recall_at_k(hits, relevant, 5) == 1.0
    assert reciprocal_rank(hits, relevant) == 1.0
    expected = (1 / math.log2(2) + 1 / math.log2(4)) / (1 / math.log2(2) + 1 / math.log2(3))
    assert math.isclose(ndcg_at_k(hits, relevant, 10), expected)


def test_metadata_filter_correctness_detects_cross_tenant_hit() -> None:
    hits = (
        RankedHit(source_id="a", metadata={"tenant_id": "t1", "authorized": True}),
        RankedHit(source_id="b", metadata={"tenant_id": "t2", "authorized": True}),
    )
    assert metadata_filter_correctness(hits, {"tenant_id": "t1", "authorized": True}) == 0.5


def test_score_observation_emits_all_metrics() -> None:
    observation = RetrievalObservation(
        case_id="retrieval-001",
        retriever="dense",
        hits=_hits("a", "b", "x"),
        relevant_source_ids=frozenset({"a", "b"}),
        required_metadata={"tenant_id": "t1", "authorized": True},
        latency_ms=12.5,
        repeat=2,
    )
    result = score_observation(observation)
    assert result.recall_at_1 == 0.5
    assert result.recall_at_5 == 1.0
    assert result.recall_at_10 == 1.0
    assert result.reciprocal_rank == 1.0
    assert result.ndcg_at_10 == 1.0
    assert result.metadata_filter_correctness == 1.0
    assert result.latency_ms == 12.5


def test_confidence_interval_and_variance_are_reported() -> None:
    stats = confidence_interval_95([0.8, 0.9, 1.0, 0.9, 0.9])
    assert stats["n"] == 5
    assert stats["variance"] > 0
    assert stats["ci95_low"] < stats["mean"] < stats["ci95_high"]


def test_compare_retrievers_reports_delta_and_repeat_statistics() -> None:
    observations = []
    for repeat in range(3):
        observations.extend(
            [
                score_observation(RetrievalObservation("r1", "dense", _hits("a", "x"), frozenset({"a", "b"}), {"tenant_id": "t1", "authorized": True}, 10, repeat)),
                score_observation(RetrievalObservation("r1", "fused", _hits("a", "b"), frozenset({"a", "b"}), {"tenant_id": "t1", "authorized": True}, 15, repeat)),
            ]
        )
    report = compare_retrievers(observations, baseline="dense")
    assert report["retrievers"]["fused"]["delta_vs_baseline"]["recall_at_5"] == 0.5
    assert report["repeated_run_statistics"]["fused"]["recall_at_5"]["n"] == 3
