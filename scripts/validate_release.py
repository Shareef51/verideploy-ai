#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
from verideploy.release_handoff import validate_final_release

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--report',default='evals/reports/final-release.json'); args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    result=validate_final_release(root)
    out=root/args.report; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2)); return 0 if result['gate']=='pass' else 1
if __name__=='__main__': raise SystemExit(main())
