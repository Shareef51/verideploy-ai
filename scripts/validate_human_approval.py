from __future__ import annotations

import json
import threading
from uuid import UUID, uuid4

from verideploy.approvals.repository import ApprovalConflictError, InMemoryApprovalRepository
from verideploy.approvals.schemas import ApprovalDecision, ApprovalRequestCreate, ApprovalRisk, ApprovalStatus, DecisionCommand, EvidenceSummary, ReviewPolicy, ReviewerContext
from verideploy.approvals.service import HumanApprovalService
from verideploy.approvals.signing import ApprovalAuditSigner

TENANT=UUID("11111111-1111-4111-8111-111111111111")
svc=HumanApprovalService(repository=InMemoryApprovalRepository(),signer=ApprovalAuditSigner("validator-signing-secret"))
request=svc.request_review(ApprovalRequestCreate(
 tenant_id=TENANT,run_id=uuid4(),investigation_id="INV-41-GATE",action_type="production.release.promote",action_payload={"release":"REL-41"},
 risk=ApprovalRisk.CRITICAL,risk_score=99,requested_by="planner",evidence_summary=EvidenceSummary(title="Critical production promotion",summary="Concurrent approval gate fixture",evidence_ids=("ev-41",),risk_factors=("production write",)),
 policy=ReviewPolicy(policy_id="critical-production",required_roles=("release_reviewer",),expiry_seconds=3600),idempotency_key="concurrency-gate",
))
before=svc.authorize_action(tenant_id=TENANT,approval_id=request.approval_id)
barrier=threading.Barrier(17); results=[]; lock=threading.Lock()
def worker(i:int):
    barrier.wait()
    command=DecisionCommand(tenant_id=TENANT,approval_id=request.approval_id,reviewer=ReviewerContext(reviewer_id=f"reviewer-{i}",roles=frozenset({"release_reviewer"})),decision=ApprovalDecision.APPROVE if i%2==0 else ApprovalDecision.REJECT,comment="concurrency gate decision",expected_version=1)
    try:
        item=svc.decide(command); outcome={"kind":"winner","status":item.status.value,"reviewer":command.reviewer.reviewer_id}
    except ApprovalConflictError:
        outcome={"kind":"conflict","reviewer":command.reviewer.reviewer_id}
    with lock: results.append(outcome)
threads=[threading.Thread(target=worker,args=(i,)) for i in range(16)]
for t in threads:t.start()
barrier.wait()
for t in threads:t.join()
final=svc.get(tenant_id=TENANT,approval_id=request.approval_id)
events=svc.events(tenant_id=TENANT,approval_id=request.approval_id)
terminal=[e for e in events if e.new_status in {ApprovalStatus.APPROVED,ApprovalStatus.REJECTED}]
after=svc.authorize_action(tenant_id=TENANT,approval_id=request.approval_id)
report={
 "valid": (before.authorized is False and len([x for x in results if x["kind"]=="winner"])==1 and len(terminal)==1 and final.status in {ApprovalStatus.APPROVED,ApprovalStatus.REJECTED} and after.authorized==(final.status==ApprovalStatus.APPROVED)),
 "concurrent_decision_attempts":16,
 "winning_terminal_decisions":len([x for x in results if x["kind"]=="winner"]),
 "conflicts":len([x for x in results if x["kind"]=="conflict"]),
 "terminal_audit_events":len(terminal),
 "authorized_before_review":before.authorized,
 "final_status":final.status.value,
 "authorized_after_review":after.authorized,
}
print(json.dumps(report,indent=2,sort_keys=True))
if not report["valid"]:raise SystemExit(1)
