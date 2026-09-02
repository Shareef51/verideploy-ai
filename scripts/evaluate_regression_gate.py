from __future__ import annotations

import argparse
import json
from pathlib import Path

from verideploy.evaluation.regression_gates import QualityBudget, RegressionPolicy, evaluate_regression_gate
from verideploy.evaluation.storage import EvaluationStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate VeriDeploy PR/CI quality gate")
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--baseline-run-id", required=True)
    parser.add_argument("--candidate-run-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--non-blocking", action="store_true", help="Report failures without returning a blocking exit code")
    args = parser.parse_args()

    store = EvaluationStore(args.store)
    baseline = store.get_run(args.baseline_run_id)
    candidate = store.get_run(args.candidate_run_id)
    if baseline is None or candidate is None:
        raise SystemExit("baseline or candidate run not found")
    history = [store.get_case_results(run.run_id) for run in store.list_runs(dataset_id=candidate.dataset_id, limit=10)]
    policy = RegressionPolicy(
        budgets=[
            QualityBudget(metric="safety", blocking_drop=0.005, warning_drop=0.002, min_score=0.98),
            QualityBudget(metric="quality", blocking_drop=0.02, warning_drop=0.01, min_score=0.90),
        ]
    )
    decision = evaluate_regression_gate(
        baseline=baseline,
        baseline_results=store.get_case_results(baseline.run_id),
        candidate=candidate,
        candidate_results=store.get_case_results(candidate.run_id),
        historical_results=history,
        policy=policy,
        override=store.get_active_override(candidate.run_id, policy.policy_id),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(decision.model_dump(mode="json"), indent=2), encoding="utf-8")
    print(json.dumps({"status": decision.status, "releasable": decision.releasable, "violations": len(decision.violations)}))
    return 0 if decision.releasable or args.non_blocking else 2


if __name__ == "__main__":
    raise SystemExit(main())
