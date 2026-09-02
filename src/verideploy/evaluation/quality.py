from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verideploy.evaluation.datasets import load_jsonl_dataset
from verideploy.evaluation.models import EvalCase

EXPECTED_COUNTS: dict[str, int] = {
    "retrieval": 100,
    "rca": 80,
    "release_risk": 80,
    "visual": 60,
    "document_qa": 60,
    "hallucination": 60,
    "citation": 60,
}
TOTAL_CASES = sum(EXPECTED_COUNTS.values())

_REQUIRED_GROUND_TRUTH_KEYS: dict[str, frozenset[str]] = {
    "retrieval": frozenset({"relevant_source_ids", "must_retrieve_at_k"}),
    "rca": frozenset({"root_cause_code", "supporting_source_ids", "prohibited_alternatives"}),
    "release_risk": frozenset({"decision", "risk_band", "supporting_source_ids"}),
    "visual": frozenset({"observations", "supporting_source_ids", "numeric_tolerance"}),
    "document_qa": frozenset({"answer", "supporting_source_ids", "required_citation_spans"}),
    "hallucination": frozenset({"verdict", "allowed_claims", "forbidden_claims", "supporting_source_ids"}),
    "citation": frozenset({"claims", "required_source_ids", "minimum_coverage"}),
}
_LEAKAGE_FIELD_NAMES = frozenset({"answer_key", "ground_truth", "expected_answer", "gold_label"})
_LEAKAGE_MARKERS = ("__ground_truth__", "__answer_key__", "gold answer:")


@dataclass(frozen=True)
class DatasetQualityIssue:
    code: str
    message: str
    case_id: str | None = None


@dataclass
class DatasetQualityReport:
    dataset_path: str
    case_count: int
    category_counts: dict[str, int]
    unique_case_ids: int
    unique_content_fingerprints: int
    issues: list[DatasetQualityIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_path": self.dataset_path,
            "case_count": self.case_count,
            "category_counts": self.category_counts,
            "unique_case_ids": self.unique_case_ids,
            "unique_content_fingerprints": self.unique_content_fingerprints,
            "passed": self.passed,
            "issues": [issue.__dict__ for issue in self.issues],
        }


def _normalized(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).lower()
    return re.sub(r"\s+", " ", text).strip()


def _fingerprint(case: EvalCase) -> str:
    # Fingerprint semantic task content, deliberately excluding IDs and provenance metadata.
    payload = f"{case.category}|{_normalized(case.input)}|{_normalized(case.ground_truth)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_ids(case: EvalCase) -> set[str]:
    return {item.source_id for item in case.source_requirements if item.required}


def _ground_truth_source_ids(case: EvalCase) -> set[str]:
    values: set[str] = set()
    for key in ("relevant_source_ids", "supporting_source_ids", "required_source_ids"):
        raw = case.ground_truth.get(key, [])
        if isinstance(raw, list):
            values.update(str(item) for item in raw)
    return values


def _validate_case(case: EvalCase) -> list[DatasetQualityIssue]:
    issues: list[DatasetQualityIssue] = []
    required_keys = _REQUIRED_GROUND_TRUTH_KEYS.get(case.category)
    if required_keys is None:
        return [DatasetQualityIssue("unknown_category", f"unsupported category {case.category}", case.case_id)]

    missing = sorted(required_keys.difference(case.ground_truth))
    if missing:
        issues.append(DatasetQualityIssue("ground_truth_missing", f"missing keys: {', '.join(missing)}", case.case_id))

    if not case.source_requirements:
        issues.append(DatasetQualityIssue("sources_missing", "source_requirements must not be empty", case.case_id))
    required_sources = _source_ids(case)
    gt_sources = _ground_truth_source_ids(case)
    if gt_sources and not gt_sources.issubset(required_sources):
        absent = sorted(gt_sources.difference(required_sources))
        issues.append(DatasetQualityIssue("source_contract_mismatch", f"ground truth sources not required: {absent}", case.case_id))

    input_keys = {str(key).lower() for key in case.input}
    leaked_fields = sorted(input_keys.intersection(_LEAKAGE_FIELD_NAMES))
    if leaked_fields:
        issues.append(DatasetQualityIssue("label_leakage_field", f"input exposes labels via {leaked_fields}", case.case_id))
    normalized_input = _normalized(case.input)
    for marker in _LEAKAGE_MARKERS:
        if marker in normalized_input:
            issues.append(DatasetQualityIssue("label_leakage_marker", f"input contains leakage marker {marker}", case.case_id))

    split = case.metadata.get("split")
    if split != "evaluation":
        issues.append(DatasetQualityIssue("split_invalid", "dataset cases must use split=evaluation", case.case_id))
    if case.metadata.get("synthetic") is not True:
        issues.append(DatasetQualityIssue("provenance_invalid", "dataset cases must be marked synthetic", case.case_id))
    return issues


def validate_dataset(path: Path) -> DatasetQualityReport:
    cases = load_jsonl_dataset(path)
    category_counts = dict(sorted(Counter(case.category for case in cases).items()))
    issues: list[DatasetQualityIssue] = []

    if len(cases) != TOTAL_CASES:
        issues.append(DatasetQualityIssue("case_count", f"expected {TOTAL_CASES}, got {len(cases)}"))
    if category_counts != dict(sorted(EXPECTED_COUNTS.items())):
        issues.append(DatasetQualityIssue("category_counts", f"expected {EXPECTED_COUNTS}, got {category_counts}"))

    fingerprints: dict[str, str] = {}
    for case in cases:
        fp = _fingerprint(case)
        prior = fingerprints.get(fp)
        if prior is not None:
            issues.append(DatasetQualityIssue("semantic_duplicate", f"duplicates semantic content of {prior}", case.case_id))
        else:
            fingerprints[fp] = case.case_id
        issues.extend(_validate_case(case))

    return DatasetQualityReport(
        dataset_path=str(path),
        case_count=len(cases),
        category_counts=category_counts,
        unique_case_ids=len({case.case_id for case in cases}),
        unique_content_fingerprints=len(fingerprints),
        issues=issues,
    )


def assert_dataset_quality(path: Path) -> DatasetQualityReport:
    report = validate_dataset(path)
    if not report.passed:
        detail = "; ".join(f"{issue.code}:{issue.case_id or '-'}:{issue.message}" for issue in report.issues[:20])
        raise ValueError(f"dataset quality gate failed: {detail}")
    return report
