from pathlib import Path
import json
from verideploy.topology.schemas import TopologySnapshot
from verideploy.topology.seed import build_nexuspay_topology
from verideploy.topology.validation import validate_topology

root=Path(__file__).resolve().parents[1]
path=root/"data"/"topology"/"nexuspay-topology.json"
stored=TopologySnapshot.model_validate_json(path.read_text(encoding="utf-8"))
report=validate_topology(stored)
errors=list(report.errors)
if stored != build_nexuspay_topology(): errors.append("stored topology differs from deterministic generator")
final=report.model_copy(update={"valid":not errors,"errors":tuple(errors)})
(root/"artifacts"/"topology-validation.json").write_text(json.dumps(final.model_dump(mode="json"),indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps(final.model_dump(mode="json"),sort_keys=True))
if not final.valid: raise SystemExit(1)
