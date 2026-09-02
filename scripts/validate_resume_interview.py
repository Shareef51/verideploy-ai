#!/usr/bin/env python3
from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from verideploy.career.interview_evidence import build_report, write_markdown
report=build_report(ROOT)
write_markdown(ROOT, report)
out=ROOT/"evals/reports/resume-interview-evidence.json"
out.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps({k: report[k] for k in ("release","gate","measured_metrics","findings")}, indent=2))
raise SystemExit(0 if report["gate"]=="pass" else 1)
