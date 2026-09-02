from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.schemas import CreateInvestigationCommand, InvestigationStatus
from verideploy.investigations.service import InvestigationService
from verideploy.postmortems.repository import SqlAlchemyPostmortemRepository
from verideploy.postmortems.schemas import (
    ApprovalDecision, Citation, CreatePostmortemCommand, ReviewPostmortemCommand, ReviewedEvidenceBundle, TimelineEntry,
)
from verideploy.postmortems.service import PostmortemEligibilityError, PostmortemService


def stack(tmp_path):
    url=f"sqlite:///{tmp_path/'.db'}"
    investigations=InvestigationService(SqlAlchemyInvestigationRepository(url, create_schema=True))
    postmortems=PostmortemService(SqlAlchemyPostmortemRepository(url, create_schema=True), investigations)
    return investigations, postmortems


def completed_investigation(service: InvestigationService, tenant, user):
    cmd=CreateInvestigationCommand(investigation_id=uuid4(),tenant_id=tenant,requested_by=user,idempotency_key="incident-001",query="Why did checkout latency increase after the production deployment?")
    record,_=service.accept(cmd); service.initialize(tenant,record.investigation_id)
    return service._repository.transition(tenant,record.investigation_id,InvestigationStatus.COMPLETED)  # lifecycle fixture


def command(investigation, user):
    evidence=["ev-log-001","ev-trace-001","ev-release-001"]
    bundle=ReviewedEvidenceBundle(
        reviewed_by=user,reviewed_at=datetime.now(UTC)+timedelta(seconds=1),evidence_ids=evidence,
        timeline=[TimelineEntry(occurred_at=datetime.now(UTC),summary="Release completed before latency regression",evidence_ids=["ev-release-001"]),TimelineEntry(occurred_at=datetime.now(UTC),summary="Database waits increased after deployment",evidence_ids=["ev-trace-001","ev-log-001"])],
        root_cause="The reviewed evidence identifies database connection-pool exhaustion after the deployment.",root_cause_category="database_capacity",confidence=0.91,
        contributing_factors=["connection limit too low for new concurrency"],impact="Checkout requests experienced elevated latency and intermittent timeout responses.",
        remediation_actions=["Restore the previous connection-pool configuration"],prevention_actions=["Add release checks for database pool saturation"],limitations=["No packet capture was available"],
        citations=[Citation(claim="Latency regression followed the release",evidence_ids=["ev-release-001","ev-trace-001"]),Citation(claim="Database pool pressure is the reviewed root cause",evidence_ids=["ev-log-001","ev-trace-001"])],
    )
    return CreatePostmortemCommand(postmortem_id=uuid4(),tenant_id=investigation.tenant_id,investigation_id=investigation.investigation_id,requested_by=user,correlation_id=investigation.correlation_id,idempotency_key="postmortem-001",title="Checkout latency incident postmortem",reviewed_evidence=bundle)


def test_incomplete_investigation_cannot_generate_postmortem(tmp_path):
    investigations,postmortems=stack(tmp_path); tenant,user=uuid4(),uuid4()
    cmd=CreateInvestigationCommand(investigation_id=uuid4(),tenant_id=tenant,requested_by=user,idempotency_key="incident-002",query="Investigate a production incident using available evidence sources.")
    inv,_=investigations.accept(cmd)
    with pytest.raises(PostmortemEligibilityError): postmortems.create(command(inv,user))


def test_reviewed_completed_investigation_generates_idempotent_postmortem(tmp_path):
    investigations,postmortems=stack(tmp_path); tenant,user=uuid4(),uuid4(); inv=completed_investigation(investigations,tenant,user); cmd=command(inv,user)
    first,created=postmortems.create(cmd); second,created2=postmortems.create(cmd)
    assert created is True and created2 is False and first.postmortem_id==second.postmortem_id
    assert first.status.value=="PENDING_APPROVAL" and first.source_investigation_version==inv.version


def test_approval_makes_final_export_available_and_record_immutable(tmp_path):
    investigations,postmortems=stack(tmp_path); tenant,user=uuid4(),uuid4(); inv=completed_investigation(investigations,tenant,user); record,_=postmortems.create(command(inv,user))
    with pytest.raises(PostmortemEligibilityError): postmortems.export(tenant,record.postmortem_id,"markdown")
    approved=postmortems.review(ReviewPostmortemCommand(postmortem_id=record.postmortem_id,tenant_id=tenant,reviewer_id=user,correlation_id=record.correlation_id,decision=ApprovalDecision.APPROVE,notes="Evidence and corrective actions reviewed.",expected_version=record.version))
    exported=postmortems.export(tenant,approved.postmortem_id,"markdown")
    assert approved.status.value=="APPROVED" and "## Root cause" in exported.content and "ev-trace-001" in exported.content
    with pytest.raises(ValueError): postmortems.review(ReviewPostmortemCommand(postmortem_id=record.postmortem_id,tenant_id=tenant,reviewer_id=user,correlation_id=record.correlation_id,decision=ApprovalDecision.REJECT,notes="Late change",expected_version=approved.version))


def test_cross_tenant_postmortem_access_is_denied(tmp_path):
    investigations,postmortems=stack(tmp_path); tenant,user=uuid4(),uuid4(); inv=completed_investigation(investigations,tenant,user); record,_=postmortems.create(command(inv,user))
    assert postmortems.get(uuid4(),record.postmortem_id) is None
