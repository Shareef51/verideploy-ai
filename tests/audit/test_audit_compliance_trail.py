from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import json
import pytest
from verideploy.audit.core import (
 AuditActor,ActorType,AuditAuthorizationError,AuditIntegrityError,AuditPolicy,AuditResult,AuditSearchQuery,AuditTrail,RetentionClass,utcnow
)

TENANT="11111111-1111-4111-8111-111111111111"
OTHER="99999999-9999-4999-8999-999999999999"

def actor(*roles): return AuditActor(ActorType.USER,"user-63",tuple(roles))

def append(trail,tenant=TENANT,**kw):
 return trail.append(tenant_id=tenant,actor=actor("reviewer"),resource_type="release",resource_id="rel-63",action=kw.pop("action","release.review"),result=kw.pop("result",AuditResult.SUCCEEDED),correlation_id=kw.pop("correlation_id","corr-63"),source="gateway",payload=kw.pop("payload",{"authorization":"Bearer top-secret","safe":"ok"}),**kw)

def test_append_only_hash_chain_redacts_secrets_and_detects_tampering():
 t=AuditTrail(); a=append(t); b=append(t,action="release.approve")
 assert a.payload["authorization"]=="[REDACTED]" and a.payload["safe"]=="ok"
 assert b.previous_hash==a.event_hash and t.verify_chain(TENANT)
 t._events[0]=replace(a,payload={"safe":"tampered"})
 with pytest.raises(AuditIntegrityError): t.verify_chain(TENANT)

def test_review_signature_is_bound_to_event_hash_and_reviewer():
 t=AuditTrail(); e=append(t); signed=t.sign_review(e.audit_id,reviewer_id="reviewer-63",key_id="kms/audit/63",signing_key=b"signing-key")
 assert t.verify_review_signature(signed,b"signing-key")
 assert not t.verify_review_signature(signed,b"wrong-key")

def test_search_is_tenant_scoped_and_export_requires_privileged_role():
 t=AuditTrail(); append(t); append(t,tenant=OTHER,correlation_id="other-corr")
 q=AuditSearchQuery(tenant_id=TENANT,requester_id="u",requester_roles=("viewer",),limit=20)
 rows=t.search(q); assert len(rows)==1 and rows[0].tenant_id==TENANT
 with pytest.raises(AuditAuthorizationError): t.export(q)
 x=t.export(replace(q,requester_roles=("auditor",)),format="jsonl")
 assert x.event_count==1 and "top-secret" not in x.content and len(x.sha256)==64

def test_retention_and_legal_hold_make_purge_eligibility_explicit():
 policy=AuditPolicy(standard_days=1,security_days=10); t=AuditTrail(policy); old=utcnow()-timedelta(days=2)
 expired=t.append(tenant_id=TENANT,actor=actor("security_admin"),resource_type="session",resource_id="s1",action="session.logout",result=AuditResult.SUCCEEDED,correlation_id="c1",source="gateway",occurred_at=old)
 held=t.append(tenant_id=TENANT,actor=actor("security_admin"),resource_type="incident",resource_id="i1",action="incident.close",result=AuditResult.SUCCEEDED,correlation_id="c2",source="gateway",occurred_at=old,legal_hold=True)
 purge=t.eligible_for_purge(); assert expired in purge and held not in purge

def test_migration_ui_policy_and_routes_exist():
 root=Path(__file__).parents[2]
 migration=(root/"src/verideploy/database/migrations/versions/0026_audit_compliance_trail.py").read_text()
 assert "BEFORE UPDATE OR DELETE ON audit_compliance_events" in migration
 assert "ENABLE ROW LEVEL SECURITY" in migration and "event_hash" in migration and "legal_hold" in migration
 policy=json.loads((root/"config/audit/policy.json").read_text()); assert policy["append_only"] is True and "auditor" in policy["export_roles"]
 viewer=(root/"apps/web/components/audit/audit-viewer.tsx").read_text(); assert "AgGridReact" in viewer and "correlation_id" in viewer and "event_hash" in viewer
 assert (root/"services/ai/routes/audit.py").exists() and (root/"apps/gateway/src/audit/audit.controller.ts").exists()
