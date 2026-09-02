from __future__ import annotations

from verideploy.evaluation.models import BaselineComparison, RunManifest


def compare_runs(baseline: RunManifest, candidate: RunManifest, *, tolerance: float = 0.0) -> BaselineComparison:
    if baseline.dataset_id != candidate.dataset_id:
        raise ValueError("baseline and candidate datasets differ")
    delta = candidate.aggregate_score - baseline.aggregate_score
    return BaselineComparison(
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        baseline_score=baseline.aggregate_score,
        candidate_score=candidate.aggregate_score,
        delta=delta,
        regression=delta < -abs(tolerance),
        tolerance=abs(tolerance),
    )
