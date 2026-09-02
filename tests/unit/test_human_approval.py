from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from services.ai.main import app
from services.ai.approvals import get_approval_service
from verideploy.approvals.repository import ApprovalConflictError, InMemoryApprovalRepository
from verideploy.approvals.runtime import ApprovalRuntimeBridge
from verideploy.approvals.schemas import (
    ApprovalDecision, ApprovalRequestCreate, ApprovalRisk, ApprovalStatus, DecisionCommand,
    DelegationCommand, EvidenceSummary, ReviewPolicy, ReviewerContext,
)
from verideploy.approvals.service import ApprovalPermissionError, HumanApprovalService
from verideploy.approvals.signing import ApprovalAuditSigner, canonical_event_payload
from verideploy.graphs.memory_repository import InMemoryGraphRuntimeRepository
from verideploy.graphs.runtime import GraphDefinition, GraphRegistry, GraphRunStatus, LangGraphRuntime

TENANT = UUID("11111111-1111-4111-8111-111111111111")


def make_service() -> HumanApprovalService:
    return HumanApprovalService(repository=InMemoryApprovalRepository(), signer=ApprovalAuditSigner("test-signing-secret"))


def payload(*, run_id=None, idem="high-risk-action-0001", expiry=3600) -> ApprovalRequestCreate:
    return ApprovalRequestCreate(
        tenant_id=TENANT, run_id=run_id or uuid4(), investigation_id="INV-41", action_type="release.promote.production",
        action_payload={"release_id": "REL-41"}, risk=ApprovalRisk.HIGH, risk_score=92, requested_by="planner-agent",
        evidence_summary=EvidenceSummary(title="Production promotion", summary="Release has elevated risk after checkout changes.", evidence_ids=("ev-1",), citation_ids=("cit-1",), risk_factors=("database migration",)),
        policy=ReviewPolicy(policy_id="production-release", min_risk_score=80, required_roles=("release_reviewer",), expiry_seconds=expiry),
        idempotency_key=idem,
    )


def reviewer(name="reviewer-a", roles=("release_reviewer",)) -> ReviewerContext:
    return ReviewerContext(reviewer_id=name, roles=frozenset(roles))


def test_policy_requires_high_risk_and_idempotent_request():
    svc=make_service(); p=payload()
    first=svc.request_review(p); second=svc.request_review(p)
    assert first.approval_id == second.approval_id
    assert first.status == ApprovalStatus.PENDING
    assert svc.authorize_action(tenant_id=TENANT, approval_id=first.approval_id).authorized is False


def test_signed_audit_event_is_verifiable_and_contains_evidence_summary():
    svc=make_service(); item=svc.request_review(payload())
    event=svc.events(tenant_id=TENANT, approval_id=item.approval_id)[0]
    signed={"approval_id":str(event.approval_id),"tenant_id":str(event.tenant_id),"sequence":event.sequence,"event_type":event.event_type.value,"actor_id":event.actor_id,"actor_role":event.actor_role,"payload":event.payload,"previous_status":None,"new_status":event.new_status.value,"occurred_at":event.occurred_at.isoformat()}
    assert svc.signer.verify(signed,event.signature)
    assert event.signed_payload_sha256 == __import__('hashlib').sha256(canonical_event_payload(signed)).hexdigest()
    assert event.payload["evidence_summary"]["evidence_ids"] == ["ev-1"]


def test_reviewer_role_and_rejection_comment_policy_are_enforced():
    svc=make_service(); item=svc.request_review(payload())
    with pytest.raises(ApprovalPermissionError):
        svc.decide(DecisionCommand(tenant_id=TENANT,approval_id=item.approval_id,reviewer=reviewer(roles=("viewer",)),decision=ApprovalDecision.APPROVE,expected_version=1))
    with pytest.raises(ValueError, match="rejection comment"):
        svc.decide(DecisionCommand(tenant_id=TENANT,approval_id=item.approval_id,reviewer=reviewer(),decision=ApprovalDecision.REJECT,expected_version=1))


def test_approve_reject_request_changes_and_delegation():
    svc=make_service(); item=svc.request_review(payload())
    delegated=svc.delegate(DelegationCommand(tenant_id=TENANT,approval_id=item.approval_id,reviewer=reviewer(),delegated_to="reviewer-b",expected_version=1))
    assert delegated.status == ApprovalStatus.IN_REVIEW and delegated.delegated_to == "reviewer-b"
    with pytest.raises(ApprovalPermissionError):
        svc.decide(DecisionCommand(tenant_id=TENANT,approval_id=item.approval_id,reviewer=reviewer("reviewer-a"),decision=ApprovalDecision.APPROVE,expected_version=2))
    changed=svc.decide(DecisionCommand(tenant_id=TENANT,approval_id=item.approval_id,reviewer=reviewer("reviewer-b"),decision=ApprovalDecision.REQUEST_CHANGES,comment="Add rollback proof",expected_version=2))
    assert changed.status == ApprovalStatus.CHANGES_REQUESTED
    approved=svc.decide(DecisionCommand(tenant_id=TENANT,approval_id=item.approval_id,reviewer=reviewer("reviewer-b"),decision=ApprovalDecision.APPROVE,comment="Verified",expected_version=3))
    assert approved.status == ApprovalStatus.APPROVED
    assert svc.authorize_action(tenant_id=TENANT, approval_id=item.approval_id).authorized


def test_queue_is_risk_prioritized_and_filters_reviewer_eligibility():
    svc=make_service()
    low=payload(idem="queue-0001").model_copy(update={"risk_score":81})
    high=payload(idem="queue-0002").model_copy(update={"risk_score":99})
    a=svc.request_review(low); b=svc.request_review(high)
    queue=svc.queue(tenant_id=TENANT,reviewer=reviewer())
    assert [q.approval_id for q in queue] == [b.approval_id,a.approval_id]
    assert svc.queue(tenant_id=TENANT,reviewer=reviewer(roles=("viewer",))) == []


def test_expired_approval_fails_closed():
    svc=make_service(); item=svc.request_review(payload())
    repo=svc.repository
    assert isinstance(repo,InMemoryApprovalRepository)
    key=(TENANT,item.approval_id)
    repo._requests[key]=repo._requests[key].model_copy(update={"expires_at":datetime.now(timezone.utc)-timedelta(seconds=1)})
    current=svc.get(tenant_id=TENANT,approval_id=item.approval_id)
    assert current.status == ApprovalStatus.EXPIRED
    assert svc.authorize_action(tenant_id=TENANT,approval_id=item.approval_id).authorized is False


def test_concurrent_terminal_decisions_only_one_wins_and_high_risk_never_bypasses():
    svc=make_service(); item=svc.request_review(payload())
    barrier=threading.Barrier(3); outcomes=[]; lock=threading.Lock()
    def worker(decision,who):
        barrier.wait()
        try:
            result=svc.decide(DecisionCommand(tenant_id=TENANT,approval_id=item.approval_id,reviewer=reviewer(who),decision=decision,comment="decision",expected_version=1))
            value=("ok",result.status)
        except ApprovalConflictError:
            value=("conflict",None)
        with lock: outcomes.append(value)
    threads=[threading.Thread(target=worker,args=(ApprovalDecision.APPROVE,"reviewer-a")),threading.Thread(target=worker,args=(ApprovalDecision.REJECT,"reviewer-b"))]
    [t.start() for t in threads]; barrier.wait(); [t.join() for t in threads]
    assert sum(1 for x,_ in outcomes if x=="ok") == 1
    assert sum(1 for x,_ in outcomes if x=="conflict") == 1
    final=svc.get(tenant_id=TENANT,approval_id=item.approval_id)
    assert final.status in {ApprovalStatus.APPROVED,ApprovalStatus.REJECTED}
    auth=svc.authorize_action(tenant_id=TENANT,approval_id=item.approval_id)
    assert auth.authorized == (final.status == ApprovalStatus.APPROVED)
    terminal_events=[e for e in svc.events(tenant_id=TENANT,approval_id=item.approval_id) if e.new_status in {ApprovalStatus.APPROVED,ApprovalStatus.REJECTED}]
    assert len(terminal_events) == 1


class _Graph:
    def __init__(self): self.state={}
    async def ainvoke(self,input,config=None,**kwargs): self.state={**input,"resumed":True}; return self.state
    async def aget_state(self,config): return self.state
    def astream(self,*args,**kwargs): raise NotImplementedError


@pytest.mark.asyncio
async def test_durable_interrupt_and_resume_requires_approved_review():
    graph=_Graph(); registry=GraphRegistry(); registry.register(GraphDefinition(name="approval-demo",version="1",factory=lambda _:graph))
    repo=InMemoryGraphRuntimeRepository(); runtime=LangGraphRuntime(registry=registry,repository=repo,checkpointer=object())
    run_id=uuid4(); repo.create_run(tenant_id=TENANT,run_id=run_id,thread_id=str(run_id),graph_name="approval-demo",graph_version="1",correlation_id="corr")
    svc=make_service(); bridge=ApprovalRuntimeBridge(runtime=runtime,approvals=svc)
    approval=bridge.interrupt_for_review(payload(run_id=run_id,idem="bridge-0001"))
    assert repo.get_run(tenant_id=TENANT,run_id=run_id).status == GraphRunStatus.WAITING_FOR_APPROVAL
    with pytest.raises(PermissionError):
        await bridge.resume_approved(tenant_id=TENANT,approval_id=approval.approval_id,correlation_id="corr",graph_name="approval-demo",graph_version="1",input_state={"investigation_id":"INV-41"},run_id=run_id)
    approved=svc.decide(DecisionCommand(tenant_id=TENANT,approval_id=approval.approval_id,reviewer=reviewer(),decision=ApprovalDecision.APPROVE,expected_version=1))
    record,result=await bridge.resume_approved(tenant_id=TENANT,approval_id=approved.approval_id,correlation_id="corr",graph_name="approval-demo",graph_version="1",input_state={"investigation_id":"INV-41"},run_id=run_id)
    assert record.status == GraphRunStatus.COMPLETED and result["resumed"] is True
    event_types=[e.event_type for e in repo.list_events(tenant_id=TENANT,run_id=run_id)]
    assert "graph.approval.interrupted" in event_types and "graph.approval.resume.authorized" in event_types


def test_migration_has_rls_locking_idempotency_and_append_only_audit():
    text=Path("src/verideploy/database/migrations/versions/0022_human_approval.py").read_text()
    for token in ["approval_requests","approval_events","FORCE ROW LEVEL SECURITY","uq_approval_idempotency","prevent_approval_event_mutation","validate_approval_tenant","validate_event_tenant","validate_request_transition","require_signed_transition_event","DEFERRABLE INITIALLY DEFERRED"]:
        assert token in text
    repo=Path("src/verideploy/approvals/repository.py").read_text()
    assert "FOR UPDATE" in repo and "expected_version" in repo


def test_private_approval_api_enforces_trusted_service_and_tenant():
    svc=make_service(); app.dependency_overrides[get_approval_service]=lambda:svc
    client=TestClient(app); p=payload(idem="api-000001")
    body=p.model_dump(mode="json")
    try:
        assert client.post("/internal/v1/approvals",json=body,headers={"x-tenant-id":str(TENANT)}).status_code == 401
        other=uuid4()
        assert client.post("/internal/v1/approvals",json=body,headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(other)}).status_code == 403
        created=client.post("/internal/v1/approvals",json=body,headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(TENANT)})
        assert created.status_code == 200
        approval_id=created.json()["approval_id"]
        queue=client.get("/internal/v1/approvals/queue?reviewer_id=reviewer-a&reviewer_roles=release_reviewer",headers={"x-internal-service":"verideploy-gateway","x-tenant-id":str(TENANT)})
        assert queue.status_code == 200 and queue.json()[0]["approval_id"] == approval_id
    finally:
        app.dependency_overrides.clear()


def test_version_config_and_main_wiring():
    from packaging.version import Version
    from verideploy import __version__
    assert Version(__version__) >= Version('0.41.0')
    assert 'approval_default_expiry_seconds' in Path('src/verideploy/config.py').read_text()
    main=Path('services/ai/main.py').read_text(); assert 'approvals_router' in main

def test_gateway_and_frontend_reviewer_queue_use_public_boundary():
    module=Path("apps/gateway/src/app.module.ts").read_text()
    controller=Path("apps/gateway/src/approvals/approvals.controller.ts").read_text()
    gateway=Path("apps/gateway/src/approvals/approvals.service.ts").read_text()
    web=Path("apps/web/app/(platform)/approvals/page.tsx").read_text()
    assert "ApprovalsModule" in module
    assert '@Controller("approvals")' in controller
    assert 'PrivateAiClient' in gateway
    shared=Path('apps/gateway/src/boundary/private-ai.client.ts').read_text(); assert 'private readonly serviceName="verideploy-gateway"' in shared
    assert "/internal/v1/approvals" in gateway
    assert "/api/v1/approvals" in web
    assert "/internal/v1/approvals" not in web
    assert "expected_version" in web
