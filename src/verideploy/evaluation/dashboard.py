from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

from verideploy.evaluation.models import CaseResult, RunManifest


class ExperimentDescriptor(BaseModel):
    model: str
    prompt_id: str
    prompt_version: str
    retriever: str


class MetricDelta(BaseModel):
    metric: str
    baseline: float
    candidate: float
    delta: float
    regression: bool


class CaseDrilldown(BaseModel):
    case_id: str
    category: str
    passed: bool
    score: float
    trace_id: str | None = None
    span_id: str | None = None
    correlation_id: str | None = None
    trace_url: str | None = None


class ReleaseGateDecision(BaseModel):
    passed: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    warning_reasons: list[str] = Field(default_factory=list)


class ExperimentComparison(BaseModel):
    baseline_run_id: str
    candidate_run_id: str
    baseline: ExperimentDescriptor
    candidate: ExperimentDescriptor
    aggregate_delta: float
    metric_deltas: list[MetricDelta]
    category_deltas: dict[str, float]
    release_gate: ReleaseGateDecision


class TrendPoint(BaseModel):
    run_id: str
    completed_at: datetime
    aggregate_score: float
    passed_rate: float
    model: str
    prompt_version: str
    retriever: str


class DashboardSnapshot(BaseModel):
    generated_at: datetime
    runs: list[RunManifest]
    comparison: ExperimentComparison | None
    trends: list[TrendPoint]
    cases: list[CaseDrilldown]


@dataclass(frozen=True)
class GatePolicy:
    max_aggregate_drop: float = 0.01
    max_metric_drop: float = 0.02
    min_candidate_score: float = 0.90
    max_failed_case_rate: float = 0.05


def _descriptor(run: RunManifest) -> ExperimentDescriptor:
    metadata = run.metadata or {}
    experiment = metadata.get("experiment", {})
    return ExperimentDescriptor(
        model=str(experiment.get("model", metadata.get("model", "unknown"))),
        prompt_id=str(experiment.get("prompt_id", metadata.get("prompt_id", "unknown"))),
        prompt_version=str(experiment.get("prompt_version", metadata.get("prompt_version", "unknown"))),
        retriever=str(experiment.get("retriever", metadata.get("retriever", "unknown"))),
    )


def _metric_means(results: list[CaseResult]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for result in results:
        for score in result.scores:
            values[score.evaluator].append(score.score)
    return {name: mean(scores) for name, scores in sorted(values.items()) if scores}


def _category_means(results: list[CaseResult]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for result in results:
        scores = [item.score for item in result.scores]
        if scores:
            values[result.category].append(mean(scores))
    return {name: mean(scores) for name, scores in sorted(values.items()) if scores}


def evaluate_release_gate(
    *, baseline: RunManifest, candidate: RunManifest, metric_deltas: list[MetricDelta], policy: GatePolicy
) -> ReleaseGateDecision:
    blocking: list[str] = []
    warnings: list[str] = []
    aggregate_delta = candidate.aggregate_score - baseline.aggregate_score
    failed_rate = candidate.failed_cases / candidate.total_cases if candidate.total_cases else 1.0
    if candidate.aggregate_score < policy.min_candidate_score:
        blocking.append(f"candidate aggregate {candidate.aggregate_score:.4f} below {policy.min_candidate_score:.4f}")
    if aggregate_delta < -policy.max_aggregate_drop:
        blocking.append(f"aggregate regression {aggregate_delta:.4f} exceeds {-policy.max_aggregate_drop:.4f}")
    for item in metric_deltas:
        if item.delta < -policy.max_metric_drop:
            blocking.append(f"{item.metric} regression {item.delta:.4f} exceeds {-policy.max_metric_drop:.4f}")
        elif item.delta < 0:
            warnings.append(f"{item.metric} declined {item.delta:.4f}")
    if failed_rate > policy.max_failed_case_rate:
        blocking.append(f"failed case rate {failed_rate:.4f} exceeds {policy.max_failed_case_rate:.4f}")
    return ReleaseGateDecision(passed=not blocking, blocking_reasons=blocking, warning_reasons=warnings)


def compare_runs(
    *,
    baseline: RunManifest,
    baseline_results: list[CaseResult],
    candidate: RunManifest,
    candidate_results: list[CaseResult],
    policy: GatePolicy = GatePolicy(),
) -> ExperimentComparison:
    baseline_metrics = _metric_means(baseline_results)
    candidate_metrics = _metric_means(candidate_results)
    metric_names = sorted(set(baseline_metrics) | set(candidate_metrics))
    deltas = [
        MetricDelta(
            metric=name,
            baseline=baseline_metrics.get(name, 0.0),
            candidate=candidate_metrics.get(name, 0.0),
            delta=candidate_metrics.get(name, 0.0) - baseline_metrics.get(name, 0.0),
            regression=candidate_metrics.get(name, 0.0) < baseline_metrics.get(name, 0.0),
        )
        for name in metric_names
    ]
    baseline_categories = _category_means(baseline_results)
    candidate_categories = _category_means(candidate_results)
    categories = sorted(set(baseline_categories) | set(candidate_categories))
    category_deltas = {
        name: candidate_categories.get(name, 0.0) - baseline_categories.get(name, 0.0)
        for name in categories
    }
    return ExperimentComparison(
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        baseline=_descriptor(baseline),
        candidate=_descriptor(candidate),
        aggregate_delta=candidate.aggregate_score - baseline.aggregate_score,
        metric_deltas=deltas,
        category_deltas=category_deltas,
        release_gate=evaluate_release_gate(
            baseline=baseline, candidate=candidate, metric_deltas=deltas, policy=policy
        ),
    )


def build_case_drilldown(results: list[CaseResult], trace_base_url: str = "/agent-execution") -> list[CaseDrilldown]:
    rows: list[CaseDrilldown] = []
    for result in results:
        details: dict[str, Any] = {}
        for score in result.scores:
            details.update(score.details)
        score_value = mean([score.score for score in result.scores]) if result.scores else 0.0
        trace_id = details.get("trace_id") or result.output.get("trace_id")
        span_id = details.get("span_id") or result.output.get("span_id")
        correlation_id = details.get("correlation_id") or result.output.get("correlation_id")
        trace_url = f"{trace_base_url}?trace_id={trace_id}" if trace_id else None
        rows.append(
            CaseDrilldown(
                case_id=result.case_id,
                category=result.category,
                passed=result.passed,
                score=score_value,
                trace_id=str(trace_id) if trace_id else None,
                span_id=str(span_id) if span_id else None,
                correlation_id=str(correlation_id) if correlation_id else None,
                trace_url=trace_url,
            )
        )
    return rows


def build_trends(runs: list[RunManifest]) -> list[TrendPoint]:
    completed = [run for run in runs if run.status == "completed" and run.completed_at is not None]
    completed.sort(key=lambda run: run.completed_at or run.started_at)
    return [
        TrendPoint(
            run_id=run.run_id,
            completed_at=run.completed_at or run.started_at,
            aggregate_score=run.aggregate_score,
            passed_rate=run.passed_cases / run.total_cases if run.total_cases else 0.0,
            model=_descriptor(run).model,
            prompt_version=_descriptor(run).prompt_version,
            retriever=_descriptor(run).retriever,
        )
        for run in completed
    ]
