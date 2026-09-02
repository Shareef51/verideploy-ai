from __future__ import annotations

import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from verideploy.evaluation.datasets import build_dataset_manifest, load_jsonl_dataset
from verideploy.evaluation.evaluators import load_evaluators
from verideploy.evaluation.models import CaseResult, RunManifest
from verideploy.evaluation.reproducibility import collect_reproducibility
from verideploy.evaluation.storage import EvaluationStore

Runner = Callable[[dict[str, Any]], dict[str, Any]]


def deterministic_smoke_runner(payload: dict[str, Any]) -> dict[str, Any]:
    """Paid-call-free runner used to prove evaluation plumbing locally and in CI."""
    operation = payload.get("operation")
    if operation == "release_risk":
        return {"decision": "review", "risk_level": "medium"}
    if operation == "incident_rca":
        return {"status": "investigate", "cause": "connection_pool_pressure"}
    return {"status": "unsupported"}


def run_evaluation(
    *,
    dataset_path: Any,
    dataset_id: str,
    dataset_version: str,
    description: str,
    evaluator_names: list[str],
    runner: Runner,
    runner_name: str,
    store: EvaluationStore,
    seed: int = 51,
    environment: str = "local",
) -> tuple[RunManifest, list[CaseResult]]:
    path = dataset_path
    manifest = build_dataset_manifest(path=path, dataset_id=dataset_id, version=dataset_version, description=description)
    cases = load_jsonl_dataset(path)
    evaluators = load_evaluators(evaluator_names)
    random.seed(seed)
    run = RunManifest(
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.version,
        dataset_sha256=manifest.content_sha256,
        evaluator_names=evaluator_names,
        runner_name=runner_name,
        total_cases=len(cases),
        reproducibility=collect_reproducibility(seed=seed, environment=environment),
        metadata={"dataset_manifest": manifest.model_dump(mode="json")},
    )
    results: list[CaseResult] = []
    try:
        for case in cases:
            started = time.perf_counter()
            try:
                output = runner(case.input)
                scores = [evaluator.evaluate(case, output) for evaluator in evaluators]
                passed = all(score.passed for score in scores)
                error = None
            except Exception as exc:  # evaluation must persist failures as data
                output, scores, passed, error = {}, [], False, f"{type(exc).__name__}: {exc}"
            results.append(CaseResult(case_id=case.case_id, category=case.category, output=output, scores=scores, passed=passed, latency_ms=(time.perf_counter() - started) * 1000, error=error))
        run.passed_cases = sum(r.passed for r in results)
        run.failed_cases = len(results) - run.passed_cases
        score_values = [score.score for result in results for score in result.scores]
        run.aggregate_score = sum(score_values) / len(score_values) if score_values else 0.0
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
    except Exception:
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        store.save_run(run, results)
        raise
    store.save_run(run, results)
    return run, results
