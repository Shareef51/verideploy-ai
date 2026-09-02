from __future__ import annotations
import argparse, json
from pathlib import Path
from verideploy.operations.readiness import review_operational_readiness
ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--report', default='evals/reports/production-operations.json'); a=p.parse_args()
    report=review_operational_readiness(ROOT)
    payload={"release":report.release,"passed":report.passed,"domains_checked":report.domains_checked,"critical_gaps":report.critical_gaps,"high_gaps":report.high_gaps,"findings":[f.__dict__ for f in report.findings]}
    out=ROOT/a.report; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps(payload,indent=2)); return 0 if report.passed else 1
if __name__=='__main__': raise SystemExit(main())
