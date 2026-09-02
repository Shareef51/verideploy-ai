from __future__ import annotations
import json
from pathlib import Path
from verideploy.incidents.generator import build_incident_dataset

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "data" / "incidents" / "nexuspay-incidents.json"
out.parent.mkdir(parents=True, exist_ok=True)
dataset = build_incident_dataset()
out.write_text(json.dumps(dataset.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"path": str(out), "incidents": len(dataset.incidents), "dataset_sha256": dataset.dataset_sha256}, indent=2))
