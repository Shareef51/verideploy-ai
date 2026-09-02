from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from verideploy.evaluation.models import CaseResult, EvaluationScore, ReproducibilityMetadata, RunManifest
from verideploy.evaluation.regression_gates import QualityBudget, RegressionPolicy, evaluate_regression_gate
from verideploy.evaluation.storage import EvaluationStore


def manifest(run_id: str, score: float, model: str, prompt: str, retriever: str) -> RunManifest:
    return RunManifest(
        run_id=run_id, dataset_id="ci", dataset_version="1.0.0", dataset_sha256="6"*64,
        evaluator_names=["quality","safety"], runner_name="benchmark", total_cases=100, passed_cases=100,
        failed_cases=0, aggregate_score=score, started_at=datetime(2026,8,19,6,0,tzinfo=UTC),
        completed_at=datetime(2026,8,19,6,1,tzinfo=UTC), status="completed",
        reproducibility=ReproducibilityMetadata(python_version="3.12",platform="ci",git_commit=None,git_dirty=None,seed=60,dependency_fingerprint="benchmark-regression-gates",environment="ci"),
        metadata={"experiment":{"model":model,"prompt_id":"release-risk","prompt_version":prompt,"retriever":retriever}},
    )


def results(quality: float, safety: float) -> list[CaseResult]:
    return [CaseResult(case_id=f"case-{i:03d}",category="release-risk",output={},scores=[EvaluationScore(evaluator="quality",score=quality,passed=True),EvaluationScore(evaluator="safety",score=safety,passed=True)],passed=True,latency_ms=3.0) for i in range(100)]


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        store=EvaluationStore(Path(temp)/"eval.db")
        baseline=manifest("baseline",.955,"gpt-standard","1","dense")
        candidate=manifest("candidate",.962,"gpt-standard","2","fused")
        br, cr=results(.95,.995), results(.963,.997)
        store.save_run(baseline,br); store.save_run(candidate,cr)
        policy=RegressionPolicy(budgets=[QualityBudget(metric="quality",blocking_drop=.02,warning_drop=.01,min_score=.90),QualityBudget(metric="safety",blocking_drop=.005,warning_drop=.002,min_score=.98)])
        decision=evaluate_regression_gate(baseline=baseline,baseline_results=br,candidate=candidate,candidate_results=cr,historical_results=[br,cr],policy=policy)
        if not decision.releasable or not decision.baseline_promotable:
            raise SystemExit("regression gate failed")
        store.promote_baseline(dataset_id=candidate.dataset_id,environment="ci",run_id=candidate.run_id,promoted_by="ci",reason="quality gate passed")
        promoted=store.get_baseline(dataset_id=candidate.dataset_id,environment="ci")
        payload={"gate":decision.model_dump(mode="json"),"baseline_promoted":promoted.run_id if promoted else None,"quality_budgets":"blocking_and_warning","statistical_detection":"paired_95pct_ci","flaky_handling":"variance_quarantine","change_attribution":decision.attribution.changed_dimensions}
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(payload,indent=2),encoding="utf-8")
        print(json.dumps({"status":decision.status,"baseline":promoted.run_id if promoted else None}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
