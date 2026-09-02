#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from verideploy.testing.strategy import load_strategy,validate_suite_inventory,critical_mutation_probes,coverage_gate

def main():
 p=argparse.ArgumentParser(); p.add_argument("--measured-coverage",type=float); p.add_argument("--coverage-json"); p.add_argument("--report",default="evals/reports/testing-strategy.json"); a=p.parse_args()
 s=load_strategy(ROOT); errors=validate_suite_inventory(ROOT,s); muts=critical_mutation_probes(); measured=a.measured_coverage
 if a.coverage_json:
  measured=float(json.loads((ROOT/a.coverage_json).read_text())["totals"]["percent_covered"])
 if measured is None: measured=0.0
 cov=coverage_gate(measured,float(s["coverage"]["global_min_percent"]))
 if not cov.passed: errors.append(f"coverage {cov.measured_percent:.1f}% below required {cov.required_percent:.1f}%")
 errors += [f"mutation survived: {m.name}" for m in muts if not m.killed]
 report={"passed":not errors,"coverage":{"measured_percent":cov.measured_percent,"required_percent":cov.required_percent,"passed":cov.passed},"mutations":[m.__dict__ for m in muts],"suite_count":len(s["suites"]),"ci_shards":s["ci_shards"],"errors":errors}
 rp=ROOT/a.report; rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
 print(json.dumps(report,sort_keys=True)); return 0 if not errors else 1
if __name__=="__main__": raise SystemExit(main())
