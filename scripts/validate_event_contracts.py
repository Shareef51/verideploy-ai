#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main()->int:
    proc=subprocess.run([sys.executable,'scripts/generate_contracts.py'],cwd=ROOT,env={**__import__('os').environ,'PYTHONPATH':'src'},capture_output=True,text=True)
    errors=[] if proc.returncode==0 else [proc.stdout.strip() or proc.stderr.strip()]
    manifest=json.loads((ROOT/'contracts/final/manifest.json').read_text()) if (ROOT/'contracts/final/manifest.json').exists() else {'schemas':{}}
    required={'release-risk-response.v1','rca-response.v1','evidence-reference.v1','timeline-entry.v1','review-response.v1','api-error.v1','websocket-envelope.v1','kafka-envelope.v1'}
    missing=sorted(required-set(manifest.get('schemas',{})))
    if missing: errors.append(f'missing final schemas: {missing}')
    report={'passed':not errors,'schema_count':len(manifest.get('schemas',{})),'compatibility':'BACKWARD','errors':errors}
    rp=ROOT/'evals/reports/final-response-event-schemas.json'; rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,sort_keys=True)); return 0 if not errors else 1
if __name__=='__main__': raise SystemExit(main())
