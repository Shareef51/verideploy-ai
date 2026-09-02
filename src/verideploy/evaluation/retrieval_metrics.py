from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class RankedHit:
    source_id: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalObservation:
    case_id: str
    retriever: str
    hits: tuple[RankedHit, ...]
    relevant_source_ids: frozenset[str]
    required_metadata: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    repeat: int = 0


@dataclass(frozen=True)
class RetrievalCaseMetrics:
    case_id: str
    retriever: str
    repeat: int
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    reciprocal_rank: float
    ndcg_at_10: float
    metadata_filter_correctness: float
    latency_ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "retriever": self.retriever,
            "repeat": self.repeat,
            "recall_at_1": self.recall_at_1,
            "recall_at_5": self.recall_at_5,
            "recall_at_10": self.recall_at_10,
            "mrr": self.reciprocal_rank,
            "ndcg_at_10": self.ndcg_at_10,
            "metadata_filter_correctness": self.metadata_filter_correctness,
            "latency_ms": self.latency_ms,
        }


def recall_at_k(hits: Iterable[RankedHit], relevant_source_ids: set[str] | frozenset[str], k: int) -> float:
    relevant = set(relevant_source_ids)
    if not relevant:
        return 1.0
    retrieved = {hit.source_id for hit in list(hits)[:k]}
    return len(retrieved & relevant) / len(relevant)


def reciprocal_rank(hits: Iterable[RankedHit], relevant_source_ids: set[str] | frozenset[str]) -> float:
    relevant = set(relevant_source_ids)
    for rank, hit in enumerate(hits, start=1):
        if hit.source_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(hits: Iterable[RankedHit], relevant_source_ids: set[str] | frozenset[str], k: int = 10) -> float:
    relevant = set(relevant_source_ids)
    if not relevant:
        return 1.0
    ranked = list(hits)[:k]
    dcg = sum((1.0 / math.log2(rank + 1)) for rank, hit in enumerate(ranked, start=1) if hit.source_id in relevant)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def metadata_filter_correctness(hits: Iterable[RankedHit], required_metadata: dict[str, Any]) -> float:
    if not required_metadata:
        return 1.0
    ranked = list(hits)
    if not ranked:
        return 1.0
    compliant = 0
    for hit in ranked:
        if all(hit.metadata.get(key) == value for key, value in required_metadata.items()):
            compliant += 1
    return compliant / len(ranked)


def score_observation(observation: RetrievalObservation) -> RetrievalCaseMetrics:
    return RetrievalCaseMetrics(
        case_id=observation.case_id,
        retriever=observation.retriever,
        repeat=observation.repeat,
        recall_at_1=recall_at_k(observation.hits, observation.relevant_source_ids, 1),
        recall_at_5=recall_at_k(observation.hits, observation.relevant_source_ids, 5),
        recall_at_10=recall_at_k(observation.hits, observation.relevant_source_ids, 10),
        reciprocal_rank=reciprocal_rank(observation.hits, observation.relevant_source_ids),
        ndcg_at_10=ndcg_at_k(observation.hits, observation.relevant_source_ids, 10),
        metadata_filter_correctness=metadata_filter_correctness(observation.hits, observation.required_metadata),
        latency_ms=max(0.0, observation.latency_ms),
    )


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * percentile
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    weight = pos - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def summarize_metrics(metrics: Iterable[RetrievalCaseMetrics]) -> dict[str, float | int]:
    rows = list(metrics)
    latencies = [row.latency_ms for row in rows]
    return {
        "case_observations": len(rows),
        "recall_at_1": _mean([row.recall_at_1 for row in rows]),
        "recall_at_5": _mean([row.recall_at_5 for row in rows]),
        "recall_at_10": _mean([row.recall_at_10 for row in rows]),
        "mrr": _mean([row.reciprocal_rank for row in rows]),
        "ndcg_at_10": _mean([row.ndcg_at_10 for row in rows]),
        "metadata_filter_correctness": _mean([row.metadata_filter_correctness for row in rows]),
        "latency_mean_ms": _mean(latencies),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }


def confidence_interval_95(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0, "mean": 0.0, "variance": 0.0, "stddev": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    mean = _mean(values)
    variance = statistics.variance(values) if len(values) > 1 else 0.0
    stddev = math.sqrt(variance)
    margin = 1.96 * (stddev / math.sqrt(len(values))) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": mean,
        "variance": variance,
        "stddev": stddev,
        "ci95_low": max(0.0, mean - margin),
        "ci95_high": min(1.0, mean + margin),
    }


def repeated_run_statistics(metrics: Iterable[RetrievalCaseMetrics]) -> dict[str, dict[str, dict[str, float | int]]]:
    rows = list(metrics)
    retrievers = sorted({row.retriever for row in rows})
    metric_fields = {
        "recall_at_1": lambda row: row.recall_at_1,
        "recall_at_5": lambda row: row.recall_at_5,
        "recall_at_10": lambda row: row.recall_at_10,
        "mrr": lambda row: row.reciprocal_rank,
        "ndcg_at_10": lambda row: row.ndcg_at_10,
        "metadata_filter_correctness": lambda row: row.metadata_filter_correctness,
    }
    output: dict[str, dict[str, dict[str, float | int]]] = {}
    for retriever in retrievers:
        retriever_rows = [row for row in rows if row.retriever == retriever]
        repeat_ids = sorted({row.repeat for row in retriever_rows})
        repeat_summaries: dict[str, list[float]] = {name: [] for name in metric_fields}
        for repeat_id in repeat_ids:
            repeat_rows = [row for row in retriever_rows if row.repeat == repeat_id]
            for name, getter in metric_fields.items():
                repeat_summaries[name].append(_mean([getter(row) for row in repeat_rows]))
        output[retriever] = {name: confidence_interval_95(values) for name, values in repeat_summaries.items()}
    return output


def compare_retrievers(metrics: Iterable[RetrievalCaseMetrics], *, baseline: str) -> dict[str, Any]:
    rows = list(metrics)
    grouped: dict[str, list[RetrievalCaseMetrics]] = {}
    for row in rows:
        grouped.setdefault(row.retriever, []).append(row)
    if baseline not in grouped:
        raise ValueError(f"baseline retriever not found: {baseline}")
    baseline_summary = summarize_metrics(grouped[baseline])
    comparisons: dict[str, Any] = {}
    fields = ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10", "metadata_filter_correctness", "latency_mean_ms")
    for name, retriever_rows in sorted(grouped.items()):
        summary = summarize_metrics(retriever_rows)
        comparisons[name] = {
            "summary": summary,
            "delta_vs_baseline": {field: float(summary[field]) - float(baseline_summary[field]) for field in fields},
        }
    return {"baseline": baseline, "retrievers": comparisons, "repeated_run_statistics": repeated_run_statistics(rows)}
