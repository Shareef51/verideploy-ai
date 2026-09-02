from __future__ import annotations

import os
import threading
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from verideploy.approvals.repository import ApprovalConflictError, PostgresApprovalRepository
from verideploy.approvals.schemas import ApprovalDecision, ApprovalRequestCreate, ApprovalRisk, ApprovalStatus, DecisionCommand, EvidenceSummary, ReviewPolicy, ReviewerContext
from verideploy.approvals.service import HumanApprovalService
from verideploy.approvals.signing import ApprovalAuditSigner
from verideploy.database.session import DatabaseManager

URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not URL, reason="TEST_POSTGRES_URL is required for PostgreSQL approval tests")


def _sync(url:str)->str:
    return url.replace("postgresql+asyncpg://","postgresql+psycopg://").replace("postgresql://","postgresql+psycopg://",1)


def test_postgres_concurrency_rls_signed_transition_and_append_only():
    assert URL
    url=_sync(URL);cfg=Config("alembic.ini");cfg.set_main_option("sqlalchemy.url",url);command.upgrade(cfg,"head")
    tenant,other,run_id=uuid4(),uuid4(),uuid4();engine=create_engine(url)
    with engine.begin() as conn:
        for t in (tenant,other):
            conn.execute(text("INSERT INTO tenants(tenant_id,slug,display_name) VALUES(:id,:slug,:name) ON CONFLICT DO NOTHING"),{"id":t,"slug":f"p41-{str(t)[:8]}","name":"postgres-human-approval"})
        conn.execute(text("""INSERT INTO graph_runs(run_id,tenant_id,thread_id,graph_name,graph_version,correlation_id,status,last_sequence,created_at,updated_at)
            VALUES(:run,:tenant,:thread,'live','1','corr','WAITING_FOR_APPROVAL',0,now(),now())"""),{"run":run_id,"tenant":tenant,"thread":str(run_id)})
    engine.dispose()
    db=DatabaseManager(url);svc=HumanApprovalService(repository=PostgresApprovalRepository(db),signer=ApprovalAuditSigner("postgres-signing-secret"))
    item=svc.request_review(ApprovalRequestCreate(tenant_id=tenant,run_id=run_id,investigation_id="INV-P41",action_type="production.promote",risk=ApprovalRisk.CRITICAL,risk_score=99,requested_by="planner",evidence_summary=EvidenceSummary(title="critical",summary="live gate"),policy=ReviewPolicy(policy_id="live",required_roles=("release_reviewer",)),idempotency_key="postgres-gate"))
    assert svc.get(tenant_id=other,approval_id=item.approval_id) is None
    barrier=threading.Barrier(3);results=[];lock=threading.Lock()
    def decide(decision,name):
        barrier.wait()
        try:
            r=svc.decide(DecisionCommand(tenant_id=tenant,approval_id=item.approval_id,reviewer=ReviewerContext(reviewer_id=name,roles=frozenset({"release_reviewer"})),decision=decision,comment="live concurrency",expected_version=1));out=("ok",r.status)
        except ApprovalConflictError: out=("conflict",None)
        with lock:results.append(out)
    ts=[threading.Thread(target=decide,args=(ApprovalDecision.APPROVE,"r1")),threading.Thread(target=decide,args=(ApprovalDecision.REJECT,"r2"))]
    [t.start() for t in ts];barrier.wait();[t.join() for t in ts]
    assert sum(1 for k,_ in results if k=="ok")==1 and sum(1 for k,_ in results if k=="conflict")==1
    final=svc.get(tenant_id=tenant,approval_id=item.approval_id);assert final.status in {ApprovalStatus.APPROVED,ApprovalStatus.REJECTED}
    assert len([e for e in svc.events(tenant_id=tenant,approval_id=item.approval_id) if e.new_status in {ApprovalStatus.APPROVED,ApprovalStatus.REJECTED}])==1
    with db.tenant_session(tenant) as session:
        event_id=session.execute(text("SELECT event_id FROM approval_events WHERE approval_id=:id ORDER BY sequence LIMIT 1"),{"id":item.approval_id}).scalar_one()
        with pytest.raises(DBAPIError,match="append-only"):
            session.execute(text("UPDATE approval_events SET actor_id='mutated' WHERE event_id=:id"),{"id":event_id});session.commit()
        session.rollback()
    # Naked authoritative transition without a matching signed event must fail at commit.
    second_run=uuid4()
    with db.engine.begin() as conn:
        conn.execute(text("""INSERT INTO graph_runs(run_id,tenant_id,thread_id,graph_name,graph_version,correlation_id,status,last_sequence,created_at,updated_at)
            VALUES(:run,:tenant,:thread,'live','1','corr2','WAITING_FOR_APPROVAL',0,now(),now())"""),{"run":second_run,"tenant":tenant,"thread":str(second_run)})
    second=svc.request_review(ApprovalRequestCreate(tenant_id=tenant,run_id=second_run,investigation_id="INV-P41-2",action_type="production.promote",risk=ApprovalRisk.CRITICAL,risk_score=99,requested_by="planner",evidence_summary=EvidenceSummary(title="critical-2",summary="signed transition gate"),policy=ReviewPolicy(policy_id="live",required_roles=("release_reviewer",)),idempotency_key="postgres-gate-2"))
    with pytest.raises(DBAPIError,match="matching signed audit event"):
        with db.tenant_session(tenant) as session:
            session.execute(text("UPDATE approval_requests SET status='approved',reviewer_id='bypass',version=version+1,updated_at=now() WHERE approval_id=:id"),{"id":second.approval_id});session.commit()
    db.dispose()
