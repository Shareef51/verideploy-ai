from pathlib import Path
import json
from verideploy.topology.seed import build_nexuspay_topology
from verideploy.topology.validation import validate_topology

root=Path(__file__).resolve().parents[1]
snapshot=build_nexuspay_topology(); report=validate_topology(snapshot)
if not report.valid: raise SystemExit("topology validation failed: " + "; ".join(report.errors))
out=root/"data"/"topology"/"nexuspay-topology.json"; out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(snapshot.model_dump(mode="json"),indent=2,sort_keys=True)+"\n",encoding="utf-8")
artifact=root/"artifacts"/"topology-validation.json"
artifact.write_text(json.dumps(report.model_dump(mode="json"),indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps(report.model_dump(mode="json"),sort_keys=True))
