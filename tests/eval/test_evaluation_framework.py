from pathlib import Path

import pytest

from verideploy.evaluation.baseline import compare_runs
from verideploy.evaluation.datasets import DatasetError, build_dataset_manifest, load_jsonl_dataset
from verideploy.evaluation.models import RunManifest
from verideploy.evaluation.reproducibility import collect_reproducibility
from verideploy.evaluation.runner import deterministic_smoke_runner, run_evaluation
from verideploy.evaluation.storage import EvaluationStore

DATASET = Path("evals/datasets/smoke/v1.jsonl")


def test_versioned_dataset_loads_and_hashes() -> None:
    cases = load_jsonl_dataset(DATASET)
    manifest = build_dataset_manifest(path=DATASET, dataset_id="smoke", version="1.0.0", description="smoke")
    assert len(cases) == 2
    assert manifest.case_count == 2
    assert len(manifest.content_sha256) == 64
    assert manifest.categories == {"incident_rca": 1, "release_risk": 1}


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    line = '{"case_id":"x","category":"c","input":{},"expected":{},"metadata":{}}'
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="duplicate case_id"):
        load_jsonl_dataset(path)


def test_smoke_run_persists_results(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path / "eval.sqlite3")
    run, results = run_evaluation(
        dataset_path=DATASET,
        dataset_id="smoke",
        dataset_version="1.0.0",
        description="smoke",
        evaluator_names=["exact_fields", "required_fields"],
        runner=deterministic_smoke_runner,
        runner_name="test",
        store=store,
        environment="test",
    )
    assert run.status == "completed"
    assert run.passed_cases == 2
    assert run.failed_cases == 0
    assert run.aggregate_score == 1.0
    assert all(result.passed for result in results)
    assert store.get_run(run.run_id) == run


def test_baseline_regression_detection() -> None:
    repro = collect_reproducibility(seed=51, environment="test")
    baseline = RunManifest(dataset_id="d", dataset_version="1", dataset_sha256="a", evaluator_names=["e"], runner_name="r", aggregate_score=0.95, reproducibility=repro)
    candidate = RunManifest(dataset_id="d", dataset_version="1", dataset_sha256="a", evaluator_names=["e"], runner_name="r", aggregate_score=0.90, reproducibility=repro)
    comparison = compare_runs(baseline, candidate, tolerance=0.01)
    assert comparison.delta == pytest.approx(-0.05)
    assert comparison.regression is True


def test_reproducibility_metadata_is_complete() -> None:
    metadata = collect_reproducibility(seed=123, environment="ci")
    assert metadata.seed == 123
    assert metadata.environment == "ci"
    assert len(metadata.dependency_fingerprint) == 64
