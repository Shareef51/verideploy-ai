from pathlib import Path
import json
from verideploy.multimodal.checkpoint.integration import run_checkpoint
ROOT=Path(__file__).resolve().parents[1]
report=run_checkpoint(ROOT)
out=ROOT/'evals/reports/multimodal-integration.json'
out.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
print(json.dumps({"passed":report["passed"],"clean":report["clean"],"partial":report["partial"]}, indent=2))
raise SystemExit(0 if report["passed"] else 1)
