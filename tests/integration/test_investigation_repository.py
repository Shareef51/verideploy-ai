from uuid import uuid4

import pytest

from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.schemas import CreateInvestigationCommand, InvestigationStatus
from verideploy.investigations.service import InvestigationService


def command(tenant_id=None, key="incident-replay-001") -> CreateInvestigationCommand:
    return CreateInvestigationCommand(
        investigation_id=uuid4(), tenant_id=tenant_id or uuid4(), requested_by=uuid4(),
        idempotency_key=key, query="Why did checkout latency increase after the production release?",
        incident_id="INC-2026-0042",
    )


def test_investigation_is_idempotent_and_replay_is_ordered(tmp_path) -> None:
    repo = SqlAlchemyInvestigationRepository(f"sqlite:///{tmp_path / 'investigations.db'}", create_schema=True)
    service = InvestigationService(repo)
    cmd = command()
    first, created = service.accept(cmd)
    second, created_again = service.accept(cmd.model_copy(update={"investigation_id": uuid4()}))
    assert created is True and created_again is False
    assert second.investigation_id == first.investigation_id

    running, emitted = service.initialize(first.tenant_id, first.investigation_id)
    assert running.status == InvestigationStatus.RUNNING
    assert [event.sequence_number for event in emitted] == [1, 2, 3]
    assert [event.sequence_number for event in service.events(first.tenant_id, first.investigation_id, after_sequence=1)] == [2, 3]
    assert service.get(first.tenant_id, first.investigation_id).last_sequence_number == 3


def test_cross_tenant_snapshot_and_event_access_is_denied_by_query_scope(tmp_path) -> None:
    repo = SqlAlchemyInvestigationRepository(f"sqlite:///{tmp_path / 'tenant.db'}", create_schema=True)
    service = InvestigationService(repo)
    cmd = command(); record, _ = service.accept(cmd); service.initialize(record.tenant_id, record.investigation_id)
    attacker_tenant = uuid4()
    assert service.get(attacker_tenant, record.investigation_id) is None
    with pytest.raises(KeyError):
        service.events(attacker_tenant, record.investigation_id)


def test_cancellation_is_durable_and_terminal(tmp_path) -> None:
    repo = SqlAlchemyInvestigationRepository(f"sqlite:///{tmp_path / 'cancel.db'}", create_schema=True)
    service = InvestigationService(repo)
    cmd = command(); record, _ = service.accept(cmd); service.initialize(record.tenant_id, record.investigation_id)
    cancelled, events = service.cancel(record.tenant_id, record.investigation_id, "Incident commander stopped investigation")
    assert cancelled.status == InvestigationStatus.CANCELLED
    assert cancelled.cancel_requested is True
    assert cancelled.cancel_reason == "Incident commander stopped investigation"
    assert [event.event_type for event in events] == ["investigation.status.changed", "investigation.cancelled"]
    assert [event.sequence_number for event in service.events(record.tenant_id, record.investigation_id)] == [1, 2, 3, 4, 5]
