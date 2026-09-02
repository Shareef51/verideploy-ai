from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from verideploy.evaluation.dashboard import GatePolicy, build_case_drilldown, build_trends, compare_runs
from verideploy.evaluation.storage import EvaluationStore

router = APIRouter(prefix="/internal/v1/evaluations", tags=["evaluations"])


def _store() -> EvaluationStore:
    return EvaluationStore(Path(os.getenv("VERIDEPLOY_EVALUATION_STORE", "data/evaluations.db")))


@router.get("/runs")
def list_runs(dataset_id: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    runs = _store().list_runs(dataset_id=dataset_id, limit=limit)
    return {"runs": [run.model_dump(mode="json") for run in runs], "trends": [point.model_dump(mode="json") for point in build_trends(runs)]}


@router.get("/runs/{run_id}/cases")
def run_cases(run_id: str) -> dict[str, object]:
    store = _store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    rows = build_case_drilldown(store.get_case_results(run_id))
    return {"run": run.model_dump(mode="json"), "cases": [row.model_dump(mode="json") for row in rows]}


@router.get("/compare")
def compare(
    baseline_run_id: str,
    candidate_run_id: str,
    max_aggregate_drop: float = Query(default=0.01, ge=0.0, le=1.0),
    max_metric_drop: float = Query(default=0.02, ge=0.0, le=1.0),
) -> dict[str, object]:
    store = _store()
    baseline = store.get_run(baseline_run_id)
    candidate = store.get_run(candidate_run_id)
    if baseline is None or candidate is None:
        raise HTTPException(status_code=404, detail="Baseline or candidate evaluation run not found")
    result = compare_runs(
        baseline=baseline,
        baseline_results=store.get_case_results(baseline_run_id),
        candidate=candidate,
        candidate_results=store.get_case_results(candidate_run_id),
        policy=GatePolicy(max_aggregate_drop=max_aggregate_drop, max_metric_drop=max_metric_drop),
    )
    return result.model_dump(mode="json")

from pydantic import BaseModel
from verideploy.evaluation.regression_gates import OverrideApproval, QualityBudget, RegressionPolicy, evaluate_regression_gate


class BaselinePromotionRequest(BaseModel):
    dataset_id: str
    environment: str
    run_id: str
    promoted_by: str
    reason: str
    baseline_run_id: str | None = None


class OverrideRequest(BaseModel):
    override_id: str
    candidate_run_id: str
    policy_id: str = "default-pr-quality-v1"
    approver: str
    reason: str
    ticket: str | None = None


@router.get("/regression-gate")
def regression_gate(baseline_run_id: str, candidate_run_id: str) -> dict[str, object]:
    store = _store()
    baseline = store.get_run(baseline_run_id)
    candidate = store.get_run(candidate_run_id)
    if baseline is None or candidate is None:
        raise HTTPException(status_code=404, detail="Baseline or candidate evaluation run not found")
    policy = RegressionPolicy(
        budgets=[
            QualityBudget(metric="safety", blocking_drop=0.005, warning_drop=0.002, min_score=0.98),
            QualityBudget(metric="quality", blocking_drop=0.02, warning_drop=0.01, min_score=0.90),
        ]
    )
    history = [store.get_case_results(run.run_id) for run in store.list_runs(dataset_id=candidate.dataset_id, limit=10)]
    decision = evaluate_regression_gate(
        baseline=baseline,
        baseline_results=store.get_case_results(baseline_run_id),
        candidate=candidate,
        candidate_results=store.get_case_results(candidate_run_id),
        historical_results=history,
        policy=policy,
        override=store.get_active_override(candidate_run_id, policy.policy_id),
    )
    return decision.model_dump(mode="json")


@router.post("/baselines/promote")
def promote_baseline(request: BaselinePromotionRequest) -> dict[str, object]:
    store = _store()
    candidate = store.get_run(request.run_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    baseline = store.get_run(request.baseline_run_id) if request.baseline_run_id else store.get_baseline(dataset_id=request.dataset_id, environment=request.environment)
    if baseline is not None and baseline.run_id != candidate.run_id:
        policy = RegressionPolicy(
            budgets=[
                QualityBudget(metric="safety", blocking_drop=0.005, warning_drop=0.002, min_score=0.98),
                QualityBudget(metric="quality", blocking_drop=0.02, warning_drop=0.01, min_score=0.90),
            ]
        )
        decision = evaluate_regression_gate(
            baseline=baseline, baseline_results=store.get_case_results(baseline.run_id),
            candidate=candidate, candidate_results=store.get_case_results(candidate.run_id), policy=policy,
            override=store.get_active_override(candidate.run_id, policy.policy_id),
        )
        if not decision.baseline_promotable:
            raise HTTPException(status_code=409, detail={"message": "Candidate is not baseline-promotable", "gate": decision.model_dump(mode="json")})
    elif candidate.status != "completed" or candidate.aggregate_score < 0.90:
        raise HTTPException(status_code=409, detail="Initial baseline must be completed with aggregate score >= 0.90")
    store.promote_baseline(
        dataset_id=request.dataset_id, environment=request.environment, run_id=request.run_id,
        promoted_by=request.promoted_by, reason=request.reason,
    )
    return {"promoted": True, "dataset_id": request.dataset_id, "environment": request.environment, "run_id": request.run_id}


@router.post("/overrides")
def create_override(request: OverrideRequest) -> dict[str, object]:
    store = _store()
    if store.get_run(request.candidate_run_id) is None:
        raise HTTPException(status_code=404, detail="Candidate evaluation run not found")
    approval = OverrideApproval(**request.model_dump())
    store.save_override(approval)
    return approval.model_dump(mode="json")
