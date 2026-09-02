from __future__ import annotations
import argparse, json
from pathlib import Path
from verideploy.security import architecture_scan

def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--root",default=".");p.add_argument("--report",default="evals/reports/security.json");a=p.parse_args()
    findings=architecture_scan(a.root); critical=[f for f in findings if f.severity=="critical"]
    report={"gate":"pass" if not critical else "fail","critical_findings":len(critical),"findings":[f.__dict__ for f in findings]}
    Path(a.report).parent.mkdir(parents=True,exist_ok=True);Path(a.report).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2));return 1 if critical else 0
if __name__=="__main__":raise SystemExit(main())
