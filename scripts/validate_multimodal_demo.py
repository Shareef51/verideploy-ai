from __future__ import annotations
import json,sys
from pathlib import Path
from verideploy.demos.multimodal import validate_multimodal_demo
R=Path(__file__).resolve().parents[1]; report=validate_multimodal_demo(R)
g=(R/'apps/gateway/src/demos/demos.service.ts').read_text(); w=(R/'apps/web/components/demos/multimodal-killer-demo.tsx').read_text(); issues=list(report['issues'])
for token in ['IngestionService','InvestigationsService','ApprovalsService','runMultimodalKiller','.ingestion.accept(','.investigations.create(','.approvals.create(']:
 if token not in g: issues.append('gateway missing '+token)
for token in ['SYNTHETIC DATA ONLY','Latency budget:','Estimated demo LLM cost:','Citations:','Review gate:']:
 if token not in w: issues.append('UI missing '+token)
if 'execution_disabled:true' not in g: issues.append('consequential action is not explicitly disabled')
report['issues']=issues; report['gate']='pass' if not issues else 'fail'; (R/'evals/reports').mkdir(parents=True,exist_ok=True); (R/'evals/reports/multimodal-killer-demo.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report,indent=2)); sys.exit(bool(issues))
