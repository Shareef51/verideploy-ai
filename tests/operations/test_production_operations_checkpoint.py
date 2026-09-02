import json
from pathlib import Path
from verideploy.operations.readiness import review_operational_readiness
ROOT=Path(__file__).resolve().parents[2]

def test_operational_review_has_no_critical_gaps():
    r=review_operational_readiness(ROOT); assert r.passed; assert r.critical_gaps==0; assert r.domains_checked>=10

def test_required_alerts_have_owner_and_runbook():
    alerts=json.loads((ROOT/'config/operations/alerts.json').read_text())['alerts']
    assert len(alerts)>=6
    for a in alerts: assert a['owner'] and (ROOT/a['runbook']).exists()

def test_kafka_ops_preserves_idempotent_replay_contract():
    text=(ROOT/'docs/operations/kafka-operations.md').read_text().lower()
    assert 'idempotent' in text and 'watermark' in text and 'dlq' in text

def test_backup_restore_evidence_is_present():
    for p in ['docs/operations/database-backup-restore.md','scripts/verify_database_restore.py','docs/operations/postgresql-ha-backup-pitr.md']:
        assert (ROOT/p).exists()

def test_incident_response_preserves_approval_audit_and_tenant_controls():
    text=(ROOT/'docs/operations/incident-response.md').read_text().lower()
    assert 'human approval' in text and 'audit' in text and 'tenant' in text and 'restore' in text
