from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class TemporalAnchor:
    expected_ms: int
    observed_ms: int


@dataclass(frozen=True)
class MultimodalObservation:
    case_id: str
    modality: str
    expected_grounding: frozenset[str] = frozenset()
    observed_grounding: frozenset[str] = frozenset()
    expected_visual_facts: frozenset[str] = frozenset()
    observed_visual_facts: frozenset[str] = frozenset()
    ocr_text_available: bool = False
    visual_reasoning_correct: bool = True
    expected_citations: frozenset[str] = frozenset()
    observed_citations: frozenset[str] = frozenset()
    temporal_anchors: tuple[TemporalAnchor, ...] = ()
    duration_ms: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MultimodalCaseMetrics:
    case_id: str
    modality: str
    image_grounding_accuracy: float | None
    visual_understanding_accuracy: float | None
    ocr_free_visual_reasoning: float | None
    multimodal_citation_correctness: float
    temporal_alignment_score: float | None
    temporal_mae_ms: float | None

    @property
    def aggregate_score(self) -> float:
        values = [
            self.image_grounding_accuracy,
            self.visual_understanding_accuracy,
            self.ocr_free_visual_reasoning,
            self.multimodal_citation_correctness,
            self.temporal_alignment_score,
        ]
        active = [float(v) for v in values if v is not None]
        return statistics.fmean(active) if active else 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "modality": self.modality,
            "image_grounding_accuracy": self.image_grounding_accuracy,
            "visual_understanding_accuracy": self.visual_understanding_accuracy,
            "ocr_free_visual_reasoning": self.ocr_free_visual_reasoning,
            "multimodal_citation_correctness": self.multimodal_citation_correctness,
            "temporal_alignment_score": self.temporal_alignment_score,
            "temporal_mae_ms": self.temporal_mae_ms,
            "aggregate_score": self.aggregate_score,
        }


def set_f1(expected: frozenset[str], observed: frozenset[str]) -> float:
    if not expected and not observed:
        return 1.0
    if not expected or not observed:
        return 0.0
    tp = len(expected & observed)
    precision = tp / len(observed)
    recall = tp / len(expected)
    return 0.0 if precision + recall == 0.0 else 2 * precision * recall / (precision + recall)


def image_grounding_accuracy(expected: frozenset[str], observed: frozenset[str]) -> float:
    return set_f1(expected, observed)


def visual_understanding_accuracy(expected: frozenset[str], observed: frozenset[str]) -> float:
    return set_f1(expected, observed)


def ocr_free_visual_reasoning(*, ocr_text_available: bool, correct: bool) -> float:
    if ocr_text_available:
        return 1.0 if correct else 0.0
    return 1.0 if correct else 0.0


def multimodal_citation_correctness(expected: frozenset[str], observed: frozenset[str]) -> float:
    return set_f1(expected, observed)


def temporal_alignment(anchors: Sequence[TemporalAnchor], *, tolerance_ms: int = 1500) -> tuple[float, float | None]:
    if not anchors:
        return 1.0, None
    errors = [abs(anchor.expected_ms - anchor.observed_ms) for anchor in anchors]
    scores = [max(0.0, 1.0 - (error / tolerance_ms)) for error in errors]
    return statistics.fmean(scores), statistics.fmean(errors)


def score_observation(obs: MultimodalObservation, *, tolerance_ms: int = 1500) -> MultimodalCaseMetrics:
    is_visual = obs.modality in {"image", "screenshot", "diagram"}
    is_temporal = obs.modality in {"audio", "video"}
    temporal_score, temporal_mae = temporal_alignment(obs.temporal_anchors, tolerance_ms=tolerance_ms)
    return MultimodalCaseMetrics(
        case_id=obs.case_id,
        modality=obs.modality,
        image_grounding_accuracy=(image_grounding_accuracy(obs.expected_grounding, obs.observed_grounding) if is_visual else None),
        visual_understanding_accuracy=(visual_understanding_accuracy(obs.expected_visual_facts, obs.observed_visual_facts) if is_visual else None),
        ocr_free_visual_reasoning=(ocr_free_visual_reasoning(ocr_text_available=obs.ocr_text_available, correct=obs.visual_reasoning_correct) if is_visual else None),
        multimodal_citation_correctness=multimodal_citation_correctness(obs.expected_citations, obs.observed_citations),
        temporal_alignment_score=(temporal_score if is_temporal else None),
        temporal_mae_ms=(temporal_mae if is_temporal else None),
    )


def _mean_defined(items: Sequence[MultimodalCaseMetrics], field: str) -> float | None:
    values = [getattr(item, field) for item in items if getattr(item, field) is not None]
    return statistics.fmean(float(v) for v in values) if values else None


def summarize_metrics(metrics: Sequence[MultimodalCaseMetrics]) -> dict[str, Any]:
    if not metrics:
        raise ValueError("metrics cannot be empty")
    by_modality: dict[str, list[MultimodalCaseMetrics]] = {}
    for metric in metrics:
        by_modality.setdefault(metric.modality, []).append(metric)
    summary: dict[str, Any] = {
        "case_count": len(metrics),
        "image_grounding_accuracy": _mean_defined(metrics, "image_grounding_accuracy"),
        "visual_understanding_accuracy": _mean_defined(metrics, "visual_understanding_accuracy"),
        "ocr_free_visual_reasoning": _mean_defined(metrics, "ocr_free_visual_reasoning"),
        "multimodal_citation_correctness": statistics.fmean(m.multimodal_citation_correctness for m in metrics),
        "temporal_alignment_score": _mean_defined(metrics, "temporal_alignment_score"),
        "temporal_mae_ms": _mean_defined(metrics, "temporal_mae_ms"),
        "aggregate_score": statistics.fmean(m.aggregate_score for m in metrics),
        "modalities": {},
    }
    for modality, rows in sorted(by_modality.items()):
        summary["modalities"][modality] = {
            "case_count": len(rows),
            "aggregate_score": statistics.fmean(r.aggregate_score for r in rows),
            "citation_correctness": statistics.fmean(r.multimodal_citation_correctness for r in rows),
            "temporal_alignment_score": _mean_defined(rows, "temporal_alignment_score"),
            "temporal_mae_ms": _mean_defined(rows, "temporal_mae_ms"),
        }
    return summary


def modality_gate(summary: Mapping[str, Any], thresholds: Mapping[str, float]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    for metric, threshold in thresholds.items():
        if metric.startswith("modality:"):
            _, modality, field = metric.split(":", 2)
            value = summary["modalities"][modality][field]
        else:
            value = summary[metric]
        if value is None:
            checks[metric] = False
        elif metric.endswith("mae_ms"):
            checks[metric] = float(value) <= threshold
        else:
            checks[metric] = float(value) >= threshold
    return {"checks": checks, "passed": all(checks.values())}
