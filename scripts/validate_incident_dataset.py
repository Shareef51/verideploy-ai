from __future__ import annotations
import json
from pathlib import Path
from verideploy.incidents.schemas import IncidentDataset
from verideploy.incidents.validation import validate_incident_dataset

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "data" / "incidents" / "nexuspay-incidents.json"
artifact = ROOT / "artifacts" / "dataset-validation.json"
dataset = IncidentDataset.model_validate(json.loads(source.read_text(encoding="utf-8")))
report = validate_incident_dataset(dataset)
artifact.write_text(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
raise SystemExit(0 if report.valid else 1)
