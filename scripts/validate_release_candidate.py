from __future__ import annotations
import argparse,json
from pathlib import Path
from verideploy.release_candidate.checkpoint import evaluate_release_candidate
ROOT=Path(__file__).resolve().parents[1]
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--report',default='evals/reports/release-candidate.json');a=p.parse_args()
 r=evaluate_release_candidate(ROOT)
 payload={'release':r.release,'status':r.status,'critical_failures':r.critical_failures,'ci_browser_required':r.ci_browser_required,'gates':[g.__dict__ for g in r.gates]}
 out=ROOT/a.report;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,indent=2)+'\n')
 print(json.dumps(payload,indent=2));return 0 if r.critical_failures==0 else 1
if __name__=='__main__':raise SystemExit(main())
