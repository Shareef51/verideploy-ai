from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from verideploy.evaluation.models import DatasetManifest, EvalCase


class DatasetError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl_dataset(path: Path) -> list[EvalCase]:
    if not path.exists():
        raise DatasetError(f"dataset not found: {path}")
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            case = EvalCase.model_validate_json(raw)
        except Exception as exc:
            raise DatasetError(f"invalid case at line {line_no}: {exc}") from exc
        if case.case_id in seen:
            raise DatasetError(f"duplicate case_id: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise DatasetError("dataset contains no cases")
    return cases


def build_dataset_manifest(*, path: Path, dataset_id: str, version: str, description: str) -> DatasetManifest:
    cases = load_jsonl_dataset(path)
    categories = dict(sorted(Counter(case.category for case in cases).items()))
    return DatasetManifest(
        dataset_id=dataset_id,
        version=version,
        description=description,
        created_at=datetime.now(UTC),
        content_sha256=_sha256(path),
        case_count=len(cases),
        categories=categories,
        source_file=str(path),
    )
