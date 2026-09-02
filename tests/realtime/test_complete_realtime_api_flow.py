from __future__ import annotations
import asyncio
from uuid import uuid4
from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.schemas import CreateInvestigationCommand
from verideploy.investigations.service import InvestigationService
from verideploy.realtime.flow import reconcile_event_stream, validate_terminal_flow
from workers.investigation.investigation_worker import handle_create


def test_incident_worker_completes_rca_with_citations_audit_and_order(tmp_path):
    service=InvestigationService(SqlAlchemyInvestigationRepository(f"sqlite:///{tmp_path/'i.db'}", create_schema=True))
    cmd=CreateInvestigationCommand(investigation_id=uuid4(),tenant_id=uuid4(),requested_by=uuid4(),idempotency_key="incident",query="Why did checkout latency increase immediately after the release?")
    emitted=[]
    async def emit(t,p): emitted.append((t,p))
    asyncio.run(handle_create(cmd.model_dump_json().encode(),service,emit,complete_workflow=True))
    record=service.get(cmd.tenant_id,cmd.investigation_id); assert record and record.status.value=="COMPLETED"
    events=service.events(cmd.tenant_id,cmd.investigation_id)
    assert [e.sequence_number for e in events]==list(range(1,len(events)+1))
    projection=service.projection(cmd.tenant_id,cmd.investigation_id)
    assert projection.root_cause and projection.root_cause.determined
    assert {x.citation_id for x in projection.evidence_map} >= {"cit-deployment","cit-runtime"}
    assert any(e.event_type=="audit.recorded" for e in events)

def test_reconnect_reconciliation_handles_duplicates_and_out_of_order():
    stream=[{"sequence_number":3},{"sequence_number":1},{"sequence_number":2},{"sequence_number":2},{"sequence_number":5},{"sequence_number":4}]
    result=reconcile_event_stream(stream,authoritative_high_watermark=5)
    assert result.converged and result.applied_sequences==(1,2,3,4,5) and result.duplicate_sequences==(2,)

def test_reconciliation_detects_missing_gap():
    result=reconcile_event_stream([{"sequence_number":1},{"sequence_number":3}],authoritative_high_watermark=3)
    assert not result.converged and result.missing_sequences==(2,)

def test_terminal_release_flow_requires_state_citations_audit_and_ui():
    stages=["browser.command","nestjs.validation","kafka.command","worker.consume","langgraph.release_risk","persistence","kafka.event","redis.websocket","browser.reconcile"]
    assert validate_terminal_flow(workflow="release_risk",stages=stages,status="COMPLETED",citations=["cit-risk"],audit_events=1,ui_status="COMPLETED")==[]

def test_terminal_incident_flow_rejects_missing_citations_or_ui_drift():
    stages=["browser.command","nestjs.validation","kafka.command","worker.consume","langgraph.incident_rca","citations","audit","persistence","kafka.event","redis.websocket","browser.reconcile"]
    errors=validate_terminal_flow(workflow="incident_rca",stages=stages,status="COMPLETED",citations=[],audit_events=1,ui_status="RUNNING")
    assert "terminal result must contain citations" in errors and "final UI must match authoritative status" in errors
