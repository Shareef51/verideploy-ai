from __future__ import annotations
import json
from pathlib import Path
from verideploy.database.performance import ExplainPlanPolicy

CFG=Path('config/load/postgres-load.json')

def main() -> None:
    data=json.loads(CFG.read_text())
    thresholds=data['thresholds']
    policy=ExplainPlanPolicy(
        max_execution_ms=thresholds['explain_max_execution_ms'],
        max_total_cost=thresholds['explain_max_total_cost'],
        forbid_seq_scan_above_rows=thresholds['forbid_seq_scan_above_rows'],
    )
    assert data['query_workers'] >= 8
    assert data['incidents_per_tenant'] >= 1000
    assert 0 < thresholds['error_rate'] <= 0.05
    print(json.dumps({'valid': True, 'query_workers': data['query_workers'], 'policy': policy.__dict__ if hasattr(policy,'__dict__') else {
        'max_execution_ms': policy.max_execution_ms,'max_total_cost':policy.max_total_cost,'forbid_seq_scan_above_rows':policy.forbid_seq_scan_above_rows}}, indent=2))

if __name__=='__main__': main()
