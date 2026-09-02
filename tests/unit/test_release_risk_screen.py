from __future__ import annotations
from packaging.version import Version
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'apps/web'; GATE=ROOT/'apps/gateway'; SCREEN=WEB/'components/release-risk/release-risk-screen.tsx'

def test_version_and_ag_grid_dependencies():
    assert Version((ROOT/'src/verideploy/__init__.py').read_text().split('\"')[1]) >= Version('0.45.0')
    pkg=json.loads((WEB/'package.json').read_text()); assert Version(pkg['version']) >= Version('0.45.0')
    assert 'ag-grid-react' in pkg['dependencies'] and 'ag-grid-community' in pkg['dependencies']

def test_release_selector_and_authoritative_gateway_queries():
    s=SCREEN.read_text(); assert 'Release selector' in s
    assert '/api/v1/releases/risk-assessments?limit=50' in s
    assert 'releaseRiskListSchema' in s and 'releaseRiskRecordSchema' in s
    assert '/internal/v1' not in s and 'AI_SERVICE_BASE_URL' not in s

def test_live_risk_sse_updates_query_cache():
    s=SCREEN.read_text(); assert 'streamGatewaySse' in s
    assert 'release.risk.completed' in s and 'release.risk.started' in s
    assert 'setQueryData' in s and 'invalidateQueries' in s
    ctrl=(GATE/'src/releases/releases.controller.ts').read_text(); kafka=(GATE/'src/releases/release-risk.kafka.ts').read_text()
    assert '@Sse("risk-assessments/:assessmentId/stream")' in ctrl
    assert 'verideploy.events.release-risk.v1' in kafka and 'events$' in kafka

def test_changed_files_and_risk_factors_use_ag_grid():
    s=SCREEN.read_text(); assert s.count('AgGridReact') >= 3
    for token in ['Changed files','Risk factors & score breakdown','getRowId={p=>p.data.path}','getRowId={p=>p.data.code}']:
        assert token in s

def test_live_row_reconciliation_preserves_grid_sort_and_filter_state():
    s=SCREEN.read_text();
    block=s[s.index('function reconcileRiskFactorRows'):s.index('function download')]
    for token in ['getFilterModel','getColumnState','applyTransaction','setFilterModel','applyColumnState']:
        assert token in block
    assert 'setGridOption("rowData"' not in block

def test_score_breakdown_evidence_drawer_review_gate_and_export():
    s=SCREEN.read_text()
    for token in ['Risk score','Confidence','Evidence drawer','/approvals','requires_human_review','CSV','JSON','exportCsv','exportJson']:
        assert token in s

def test_stale_state_indicator_is_time_bounded_and_live_aware():
    s=SCREEN.read_text(); assert 'Stale live state' in s and 'tick-lastLiveAt>15000' in s
    assert '["ACCEPTED","QUEUED","RUNNING"]' in s

def test_release_file_metadata_is_real_persisted_input_not_mock_rows():
    schema=(ROOT/'src/verideploy/releases/schemas.py').read_text(); repo=(ROOT/'src/verideploy/releases/repository.py').read_text(); migration=(ROOT/'src/verideploy/database/migrations/versions/0024_release_risk_screen.py').read_text()
    assert 'class ChangedFileInput' in schema and 'changed_file_details' in schema
    assert 'changed_files_json' in repo and 'changed_files_json' in migration
    assert 'changed_file_details length must equal policy.changed_files' in schema

def test_release_selector_private_api_is_tenant_scoped_and_gateway_only():
    route=(ROOT/'services/ai/routes/releases.py').read_text(); service=(GATE/'src/releases/releases.service.ts').read_text()
    assert '@router.get("/assessments", response_model=list[ReleaseRiskRecord])' in route
    assert 'x_tenant_id: UUID = Header()' in route and 'verideploy-gateway' in route
    assert '/internal/v1/releases/assessments?limit=' in service

def test_public_contract_exposes_selector_and_sse_but_no_private_routes():
    contract=(ROOT/'contracts/openapi/gateway.yaml').read_text()
    assert Version(contract.split('version: ',1)[1].splitlines()[0].strip()) >= Version('0.45.0')
    assert 'listReleaseRiskAssessments' in contract and 'streamReleaseRiskAssessment' in contract
    assert '/internal/v1/' not in contract

def test_no_mock_or_legacy_release_risk_screen_path():
    page=(WEB/'app/(platform)/release-risk/page.tsx').read_text(); s=SCREEN.read_text().lower()
    assert 'ReleaseRiskScreen' in page and 'legacygrid' not in s
    for forbidden in ['mock data','demo risk','fake success','settimeout(resolve=>settimeout']:
        assert forbidden not in s
