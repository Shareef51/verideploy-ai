from pathlib import Path
import json
from verideploy.architecture.integrity import validate_architecture
ROOT=Path(__file__).resolve().parents[1]
report=validate_architecture(ROOT)
out=ROOT/"evals/reports/scope-architecture-integrity.json"
out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2));raise SystemExit(0 if report["valid"] else 1)
