#!/usr/bin/env python3
from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from verideploy.career.mapping import build_report
report=build_report(ROOT)
out=ROOT/"evals/reports/ai-engineering-jd-mapping.json"
out.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
raise SystemExit(0 if report["gate"]=="pass" else 1)
