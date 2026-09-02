from __future__ import annotations

import argparse
from pathlib import Path

from verideploy.evaluation.runner import deterministic_smoke_runner, run_evaluation
from verideploy.evaluation.storage import EvaluationStore


def main() -> int:
    parser = argparse.ArgumentParser(description="VeriDeploy evaluation worker one-shot executor")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--store", type=Path, default=Path("artifacts/evaluation/results.sqlite3"))
    parser.add_argument("--environment", default="worker")
    args = parser.parse_args()
    run, _ = run_evaluation(
        dataset_path=args.dataset,
        dataset_id="smoke",
        dataset_version="1.0.0",
        description="Worker-executed smoke evaluation",
        evaluator_names=["exact_fields", "required_fields"],
        runner=deterministic_smoke_runner,
        runner_name="evaluation_worker:deterministic_smoke_runner",
        store=EvaluationStore(args.store),
        environment=args.environment,
    )
    print(run.model_dump_json(indent=2))
    return 0 if run.failed_cases == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
