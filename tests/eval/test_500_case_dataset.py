from __future__ import annotations

import json
from pathlib import Path

from verideploy.evaluation.datasets import load_jsonl_dataset
from verideploy.evaluation.quality import EXPECTED_COUNTS, TOTAL_CASES, validate_dataset

DATASET = Path("evals/datasets/verideploy-500/v1.jsonl")
MANIFEST = Path("evals/datasets/verideploy-500/manifest.json")


def test_dataset_has_exact_required_shape() -> None:
    cases = load_jsonl_dataset(DATASET)
    report = validate_dataset(DATASET)
    assert len(cases) == TOTAL_CASES == 500
    assert report.category_counts == dict(sorted(EXPECTED_COUNTS.items()))
    assert report.unique_case_ids == 500
    assert report.unique_content_fingerprints == 500
    assert report.passed is True


def test_every_case_has_ground_truth_and_required_sources() -> None:
    for case in load_jsonl_dataset(DATASET):
        assert case.ground_truth
        assert case.source_requirements
        assert all(item.source_id and item.source_type for item in case.source_requirements)
        assert case.metadata["split"] == "evaluation"
        assert case.metadata["synthetic"] is True


def test_manifest_matches_dataset_and_records_clean_quality_gate() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["case_count"] == 500
    assert manifest["categories"] == dict(sorted(EXPECTED_COUNTS.items()))
    assert len(manifest["content_sha256"]) == 64
    assert manifest["quality_gate"]["passed"] is True
    assert manifest["quality_gate"]["issues"] == []


def test_quality_gate_detects_semantic_duplicates(tmp_path: Path) -> None:
    rows = DATASET.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    second = dict(first)
    second["case_id"] = "retrieval-semantic-copy"
    candidate = tmp_path / "duplicate.jsonl"
    candidate.write_text("\n".join(rows + [json.dumps(second)]) + "\n", encoding="utf-8")
    report = validate_dataset(candidate)
    assert report.passed is False
    assert any(issue.code == "semantic_duplicate" for issue in report.issues)


def test_quality_gate_detects_label_leakage(tmp_path: Path) -> None:
    rows = DATASET.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["input"]["answer_key"] = "do-not-expose"
    candidate = tmp_path / "leak.jsonl"
    candidate.write_text(json.dumps(first) + "\n", encoding="utf-8")
    report = validate_dataset(candidate)
    assert report.passed is False
    assert any(issue.code == "label_leakage_field" for issue in report.issues)
