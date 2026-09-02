#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from verideploy.orchestration.checkpoint import run_orchestration_checkpoint
ROOT=Path(__file__).resolve().parents[1]
def main()->int:
    report=run_orchestration_checkpoint(ROOT)
    out=ROOT/'evals/reports/agentic-orchestration.json'
    out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({"gate":report["gate"],"scenario_count":report["scenario_count"],"metrics":report["metrics"]["summary"]},sort_keys=True))
    return 0 if report['gate']=='pass' else 1
if __name__=='__main__': raise SystemExit(main())
