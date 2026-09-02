from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from verideploy.knowledge.validation import validate_corpus

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts" / "corpus-validation.json"


def main() -> int:
    report = validate_corpus(ROOT / "data" / "knowledge")
    REPORT.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
