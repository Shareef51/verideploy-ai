from __future__ import annotations

import argparse
import json
from pathlib import Path

from verideploy.evaluation.quality import assert_dataset_quality


def main() -> int:
    parser = argparse.ArgumentParser(description="Run dataset quality gates")
    parser.add_argument("--dataset", type=Path, default=Path("evals/datasets/verideploy-500/v1.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("evals/reports/quality.json"))
    args = parser.parse_args()
    report = assert_dataset_quality(args.dataset)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
