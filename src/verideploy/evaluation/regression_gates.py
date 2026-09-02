from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
from statistics import mean, variance
from typing import Literal

from pydantic import BaseModel, Field

from verideploy.evaluation.dashboard import ExperimentDescriptor
from verideploy.evaluation.models import CaseResult, RunManifest


class QualityBudget(BaseModel):
    metric: str
    blocking_drop: float = Field(ge=0.0, le=1.0)
    warning_drop: float = Field(ge=0.0, le=1.0)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class RegressionPolicy(BaseModel):
    policy_id: str = "default-pr-quality-v1"
    aggregate_blocking_drop: float = 0.01
    aggregate_warning_drop: float = 0.005
    min_candidate_aggregate: float = 0.90
    max_failed_case_rate: float = 0.05
    statistical_confidence: float = 0.95
    min_paired_cases: int = 20
    flaky_variance_threshold: float = 0.01
    max_flaky_fraction: float = 0.10
    budgets: list[QualityBudget] = Field(default_factory=list)


class StatisticalRegression(BaseModel):
    metric: str
    paired_cases: int
    mean_delta: float
    variance: float
    standard_error: float
    ci_low: float
    ci_high: float
    statistically_significant_regression: bool


class ChangeAttribution(BaseModel):
    changed_dimensions: list[str]
    model_changed: bool
    prompt_changed: bool
    retriever_changed: bool
    baseline: ExperimentDescriptor
    candidate: ExperimentDescriptor


class FlakyCase(BaseModel):
    case_id: str
    variance: float
    samples: int
    excluded_from_blocking: bool = True


class GateViolation(BaseModel):
    severity: Literal["blocking", "warning"]
    code: str
    message: str
    metric: str | None = None


class OverrideApproval(BaseModel):
    override_id: str
    candidate_run_id: str
    policy_id: str
    approver: str
    reason: str
    ticket: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    def active(self, at: datetime | None = None) -> bool:
        now = at or datetime.now(UTC)
        return self.expires_at is None or self.expires_at > now


class RegressionGateDecision(BaseModel):
    policy_id: str
    baseline_run_id: str
    candidate_run_id: str
    status: Literal["pass", "warn", "block", "override"]
    releasable: bool
    baseline_promotable: bool
    violations: list[GateViolation]
    statistics: list[StatisticalRegression]
    flaky_cases: list[FlakyCase]
    flaky_fraction: float
    attribution: ChangeAttribution
    override: OverrideApproval | None = None


@dataclass(frozen=True)
class CaseMetric:
    case_id: str
    metric: str
    score: float


def _descriptor(run: RunManifest) -> ExperimentDescriptor:
    metadata = run.metadata or {}
    experiment = metadata.get("experiment", {})
    return ExperimentDescriptor(
        model=str(experiment.get("model", metadata.get("model", "unknown"))),
        prompt_id=str(experiment.get("prompt_id", metadata.get("prompt_id", "unknown"))),
        prompt_version=str(experiment.get("prompt_version", metadata.get("prompt_version", "unknown"))),
        retriever=str(experiment.get("retriever", metadata.get("retriever", "unknown"))),
    )


def attribute_change(baseline: RunManifest, candidate: RunManifest) -> ChangeAttribution:
    left, right = _descriptor(baseline), _descriptor(candidate)
    dims: list[str] = []
    model_changed = left.model != right.model
    prompt_changed = (left.prompt_id, left.prompt_version) != (right.prompt_id, right.prompt_version)
    retriever_changed = left.retriever != right.retriever
    if model_changed:
        dims.append("model")
    if prompt_changed:
        dims.append("prompt")
    if retriever_changed:
        dims.append("retriever")
    return ChangeAttribution(
        changed_dimensions=dims,
        model_changed=model_changed,
        prompt_changed=prompt_changed,
        retriever_changed=retriever_changed,
        baseline=left,
        candidate=right,
    )


def detect_flaky_cases(history: list[list[CaseResult]], threshold: float) -> list[FlakyCase]:
    values: dict[str, list[float]] = defaultdict(list)
    for run_results in history:
        for result in run_results:
            if result.scores:
                values[result.case_id].append(mean(score.score for score in result.scores))
    rows: list[FlakyCase] = []
    for case_id, scores in sorted(values.items()):
        if len(scores) < 2:
            continue
        observed_variance = variance(scores)
        if observed_variance > threshold:
            rows.append(FlakyCase(case_id=case_id, variance=observed_variance, samples=len(scores)))
    return rows


def _metric_map(results: list[CaseResult], excluded: set[str]) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = defaultdict(dict)
    for result in results:
        if result.case_id in excluded:
            continue
        for score in result.scores:
            output[score.evaluator][result.case_id] = score.score
    return output


def paired_statistics(
    baseline_results: list[CaseResult], candidate_results: list[CaseResult], excluded: set[str]
) -> list[StatisticalRegression]:
    baseline = _metric_map(baseline_results, excluded)
    candidate = _metric_map(candidate_results, excluded)
    rows: list[StatisticalRegression] = []
    for metric in sorted(set(baseline) & set(candidate)):
        shared = sorted(set(baseline[metric]) & set(candidate[metric]))
        deltas = [candidate[metric][case] - baseline[metric][case] for case in shared]
        if not deltas:
            continue
        avg = mean(deltas)
        var = variance(deltas) if len(deltas) > 1 else 0.0
        se = sqrt(var / len(deltas)) if deltas else 0.0
        # Normal 95% interval. Keeping this dependency-free makes CI deterministic.
        margin = 1.96 * se
        low, high = avg - margin, avg + margin
        rows.append(
            StatisticalRegression(
                metric=metric,
                paired_cases=len(deltas),
                mean_delta=avg,
                variance=var,
                standard_error=se,
                ci_low=low,
                ci_high=high,
                statistically_significant_regression=high < 0.0,
            )
        )
    return rows


def _metric_means(results: list[CaseResult], excluded: set[str]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for result in results:
        if result.case_id in excluded:
            continue
        for score in result.scores:
            values[score.evaluator].append(score.score)
    return {key: mean(items) for key, items in values.items() if items}


def evaluate_regression_gate(
    *,
    baseline: RunManifest,
    baseline_results: list[CaseResult],
    candidate: RunManifest,
    candidate_results: list[CaseResult],
    policy: RegressionPolicy = RegressionPolicy(),
    historical_results: list[list[CaseResult]] | None = None,
    override: OverrideApproval | None = None,
) -> RegressionGateDecision:
    flaky = detect_flaky_cases(historical_results or [], policy.flaky_variance_threshold)
    excluded = {row.case_id for row in flaky}
    total_unique = len({r.case_id for r in candidate_results})
    flaky_fraction = len(excluded) / total_unique if total_unique else 0.0
    stats = paired_statistics(baseline_results, candidate_results, excluded)
    baseline_metrics = _metric_means(baseline_results, excluded)
    candidate_metrics = _metric_means(candidate_results, excluded)
    budget_map = {budget.metric: budget for budget in policy.budgets}
    violations: list[GateViolation] = []

    aggregate_delta = candidate.aggregate_score - baseline.aggregate_score
    if candidate.aggregate_score < policy.min_candidate_aggregate:
        violations.append(GateViolation(severity="blocking", code="aggregate_floor", message=f"candidate aggregate {candidate.aggregate_score:.4f} below {policy.min_candidate_aggregate:.4f}"))
    if aggregate_delta < -policy.aggregate_blocking_drop:
        violations.append(GateViolation(severity="blocking", code="aggregate_regression", message=f"aggregate delta {aggregate_delta:.4f} exceeds blocking budget {-policy.aggregate_blocking_drop:.4f}"))
    elif aggregate_delta < -policy.aggregate_warning_drop:
        violations.append(GateViolation(severity="warning", code="aggregate_warning", message=f"aggregate delta {aggregate_delta:.4f} exceeds warning budget {-policy.aggregate_warning_drop:.4f}"))

    failed_rate = candidate.failed_cases / candidate.total_cases if candidate.total_cases else 1.0
    if failed_rate > policy.max_failed_case_rate:
        violations.append(GateViolation(severity="blocking", code="failed_case_rate", message=f"failed case rate {failed_rate:.4f} exceeds {policy.max_failed_case_rate:.4f}"))
    if flaky_fraction > policy.max_flaky_fraction:
        violations.append(GateViolation(severity="blocking", code="flaky_fraction", message=f"flaky fraction {flaky_fraction:.4f} exceeds {policy.max_flaky_fraction:.4f}"))

    for metric in sorted(set(baseline_metrics) | set(candidate_metrics)):
        budget = budget_map.get(metric, QualityBudget(metric=metric, blocking_drop=0.02, warning_drop=0.01))
        base = baseline_metrics.get(metric, 0.0)
        cand = candidate_metrics.get(metric, 0.0)
        delta = cand - base
        if cand < budget.min_score:
            violations.append(GateViolation(severity="blocking", code="metric_floor", metric=metric, message=f"{metric} score {cand:.4f} below floor {budget.min_score:.4f}"))
        if delta < -budget.blocking_drop:
            violations.append(GateViolation(severity="blocking", code="metric_regression", metric=metric, message=f"{metric} delta {delta:.4f} exceeds blocking budget {-budget.blocking_drop:.4f}"))
        elif delta < -budget.warning_drop:
            violations.append(GateViolation(severity="warning", code="metric_warning", metric=metric, message=f"{metric} delta {delta:.4f} exceeds warning budget {-budget.warning_drop:.4f}"))

    for item in stats:
        if item.paired_cases >= policy.min_paired_cases and item.statistically_significant_regression:
            # Statistical evidence is blocking only when the observed drop also breaches a budget.
            budget = budget_map.get(item.metric, QualityBudget(metric=item.metric, blocking_drop=0.02, warning_drop=0.01))
            if item.mean_delta < -budget.blocking_drop:
                violations.append(GateViolation(severity="blocking", code="statistical_regression", metric=item.metric, message=f"{item.metric} paired 95% CI [{item.ci_low:.4f}, {item.ci_high:.4f}] confirms regression"))
            elif item.mean_delta < -budget.warning_drop:
                violations.append(GateViolation(severity="warning", code="statistical_warning", metric=item.metric, message=f"{item.metric} paired 95% CI [{item.ci_low:.4f}, {item.ci_high:.4f}] indicates decline"))

    blockers = [v for v in violations if v.severity == "blocking"]
    warnings = [v for v in violations if v.severity == "warning"]
    valid_override = override is not None and override.candidate_run_id == candidate.run_id and override.policy_id == policy.policy_id and override.active()
    if blockers and valid_override:
        status: Literal["pass", "warn", "block", "override"] = "override"
        releasable = True
    elif blockers:
        status = "block"
        releasable = False
    elif warnings:
        status = "warn"
        releasable = True
    else:
        status = "pass"
        releasable = True

    return RegressionGateDecision(
        policy_id=policy.policy_id,
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        status=status,
        releasable=releasable,
        baseline_promotable=releasable and status != "override" and not blockers,
        violations=violations,
        statistics=stats,
        flaky_cases=flaky,
        flaky_fraction=flaky_fraction,
        attribution=attribute_change(baseline, candidate),
        override=override if valid_override else None,
    )
