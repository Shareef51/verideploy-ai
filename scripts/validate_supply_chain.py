from __future__ import annotations
import argparse,json
from pathlib import Path
from supply_chain.core import ROOT, build_artifact_manifest, dependency_snapshot, release_gate

def main()->int:
 p=argparse.ArgumentParser(); p.add_argument('--report',default='evals/reports/supply-chain.json'); p.add_argument('--release',action='store_true'); a=p.parse_args()
 report={'offline_validation':not a.release,'dependency_snapshot':dependency_snapshot(),'artifact_manifest':build_artifact_manifest(['package.json','pyproject.toml','config/release/version.json','config/supply-chain/policy.json']),'gate':release_gate(require_network_material=a.release)}
 out=ROOT/a.report; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report['gate'],indent=2)); return 0 if report['gate']['passed'] else 2
if __name__=='__main__': raise SystemExit(main())
