from __future__ import annotations
import json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]; c=json.loads((R/'config/demos/production-demos.json').read_text()); issues=[]
if len(c.get('scenarios',[]))!=5: issues.append('exactly five demos required')
for d in c.get('scenarios',[]):
 if not c.get('synthetic'): issues.append(f"{d.get('id')}: catalog not synthetic")
 if d.get('asset') and not (R/d['asset']).is_file(): issues.append(f"{d['id']}: missing asset")
g=(R/'apps/gateway/src/demos/demos.service.ts').read_text(); w=(R/'apps/web/components/demos/production-demos.tsx').read_text()
for token in ['ReleasesService','InvestigationsService','IngestionService']: 
 if token not in g: issues.append('missing real service '+token)
if 'SYNTHETIC DATA ONLY' not in w: issues.append('UI synthetic marker missing')
report={'gate':'pass' if not issues else 'fail','demo_count':len(c.get('scenarios',[])),'synthetic':True,'issues':issues}
(R/'evals/reports').mkdir(parents=True,exist_ok=True); (R/'evals/reports/five-production-demos.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report,indent=2)); sys.exit(bool(issues))
