from __future__ import annotations
import json
from pathlib import Path
from verideploy.audit.core import AuditActor,ActorType,AuditResult,AuditSearchQuery,AuditTrail,RetentionClass

def main():
 t=AuditTrail(); tenant="11111111-1111-4111-8111-111111111111"; actor=AuditActor(ActorType.USER,"reviewer-demo",("reviewer","auditor"))
 actions=[("release.review",AuditResult.SUCCEEDED),("approval.approve",AuditResult.SUCCEEDED),("mcp.execute",AuditResult.DENIED),("evaluation.override",AuditResult.SUCCEEDED),("postmortem.export",AuditResult.SUCCEEDED)]
 for i,(action,result) in enumerate(actions,1):
  t.append(tenant_id=tenant,actor=actor,resource_type="demo",resource_id=f"resource-{i}",action=action,result=result,correlation_id=f"corr-63-{i}",trace_id=f"{'a'*31}{i}",span_id=f"{'b'*15}{i}",source="ci",payload={"authorization":"Bearer should-never-persist","detail":"synthetic"},retention_class=RetentionClass.SECURITY if i in (2,3,4) else RetentionClass.STANDARD)
 chain_ok=t.verify_chain(tenant); q=AuditSearchQuery(tenant_id=tenant,requester_id="reviewer-demo",requester_roles=("auditor",),limit=100); export=t.export(q)
 report={"gate":"PASS" if chain_ok and len(t.events)==5 and "should-never-persist" not in export.content else "FAIL","events":len(t.events),"chain_verified":chain_ok,"redaction_verified":"should-never-persist" not in export.content,"export_sha256":export.sha256,"reconstructable_fields":["actor","resource","action","result","correlation_id","trace_id","event_hash"]}
 out=Path("evals/reports/audit-compliance.json");out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2));raise SystemExit(0 if report["gate"]=="PASS" else 1)
if __name__=="__main__":main()
