from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; S=(ROOT/'apps/web/components/release-risk/release-risk-screen.tsx').read_text(); C=(ROOT/'contracts/openapi/gateway.yaml').read_text(); G=(ROOT/'apps/gateway/src/releases/releases.controller.ts').read_text()
checks={
'release_selector':'Release selector' in S,
'ag_grid_changed_files':'Changed files' in S and 'AgGridReact<ChangedFile>' in S,
'ag_grid_risk_factors':'Risk factors & score breakdown' in S and 'AgGridReact<RiskFactor>' in S,
'live_sse':'streamGatewaySse' in S and '@Sse("risk-assessments/:assessmentId/stream")' in G,
'preserves_filter':'getFilterModel' in S and 'setFilterModel' in S,
'preserves_sort':'getColumnState' in S and 'applyColumnState' in S,
'row_transactions':'applyTransaction' in S,
'score_breakdown':'Risk score' in S and 'Confidence' in S,
'evidence_drawer':'Evidence drawer' in S,
'review_gate':'requires_human_review' in S and '/approvals' in S,
'stale_indicator':'Stale live state' in S,
'export':'exportCsv' in S and 'exportJson' in S,
'gateway_only':'/internal/v1' not in S and 'AI_SERVICE_BASE_URL' not in S,
'public_contract':'streamReleaseRiskAssessment' in C and 'listReleaseRiskAssessments' in C,
'no_private_contract':'/internal/v1/' not in C,
}
out={'valid':all(checks.values()),'checks':checks,'passed':sum(checks.values()),'total':len(checks)}
path=ROOT/'artifacts/release-risk-screen-validation.json'; path.write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps(out,indent=2)); raise SystemExit(0 if out['valid'] else 1)
