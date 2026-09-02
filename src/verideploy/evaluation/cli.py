from __future__ import annotations

import argparse
import json
from pathlib import Path

from verideploy.evaluation.baseline import compare_runs
from verideploy.evaluation.runner import deterministic_smoke_runner, run_evaluation
from verideploy.evaluation.storage import EvaluationStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verideploy-eval", description="VeriDeploy evaluation runner")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke", help="run the deterministic smoke dataset")
    smoke.add_argument("--dataset", type=Path, default=Path("evals/datasets/smoke/v1.jsonl"))
    smoke.add_argument("--store", type=Path, default=Path("artifacts/evaluation/results.sqlite3"))
    smoke.add_argument("--report", type=Path, default=Path("evals/reports/smoke-latest.json"))
    smoke.add_argument("--environment", default="local")
    smoke.add_argument("--fail-on-regression", action="store_true")
    smoke.add_argument("--tolerance", type=float, default=0.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "smoke":
        return 2
    store = EvaluationStore(args.store)
    run, _ = run_evaluation(
        dataset_path=args.dataset,
        dataset_id="smoke",
        dataset_version="1.0.0",
        description="Paid-call-free evaluation framework smoke dataset",
        evaluator_names=["exact_fields", "required_fields"],
        runner=deterministic_smoke_runner,
        runner_name="deterministic_smoke_runner",
        store=store,
        environment=args.environment,
    )
    baseline = store.latest_completed(run.dataset_id, exclude_run_id=run.run_id)
    comparison = None if baseline is None else compare_runs(baseline, run, tolerance=args.tolerance)
    store.export_run_json(run.run_id, args.report)
    summary = {"run": run.model_dump(mode="json"), "baseline_comparison": None if comparison is None else comparison.model_dump(mode="json")}
    print(json.dumps(summary, indent=2, default=str))
    if run.failed_cases:
        return 1
    if args.fail_on_regression and comparison is not None and comparison.regression:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
