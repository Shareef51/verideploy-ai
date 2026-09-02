import json
from uuid import uuid4

import pytest

from verideploy.investigations.repository import SqlAlchemyInvestigationRepository
from verideploy.investigations.schemas import CancelInvestigationCommand, CreateInvestigationCommand
from verideploy.investigations.service import InvestigationService
from workers.investigation.investigation_worker import handle_cancel, handle_create


@pytest.mark.asyncio
async def test_create_worker_persists_and_emits_replayable_events(tmp_path) -> None:
    service = InvestigationService(SqlAlchemyInvestigationRepository(f"sqlite:///{tmp_path / 'worker.db'}", create_schema=True))
    emitted: list[tuple[str, dict]] = []
    async def emit(kind: str, payload: dict) -> None: emitted.append((kind, payload))
    cmd = CreateInvestigationCommand(investigation_id=uuid4(), tenant_id=uuid4(), requested_by=uuid4(), idempotency_key="worker-investigation-001", query="Why did payment latency increase after deployment?")
    await handle_create(cmd.model_dump_json().encode(), service, emit)
    assert [kind for kind, _ in emitted] == ["investigation.created", "investigation.status.changed", "graph.node.completed"]
    assert [payload["sequence_number"] for _, payload in emitted] == [1, 2, 3]
    assert service.get(cmd.tenant_id, cmd.investigation_id).status.value == "RUNNING"


@pytest.mark.asyncio
async def test_duplicate_create_replays_existing_journal_without_duplicate_state(tmp_path) -> None:
    service = InvestigationService(SqlAlchemyInvestigationRepository(f"sqlite:///{tmp_path / 'duplicate.db'}", create_schema=True))
    cmd = CreateInvestigationCommand(investigation_id=uuid4(), tenant_id=uuid4(), requested_by=uuid4(), idempotency_key="worker-investigation-dup", query="Why did payment latency increase after deployment?")
    first: list[tuple[str, dict]] = []; second: list[tuple[str, dict]] = []
    async def emit_first(kind: str, payload: dict) -> None: first.append((kind,payload))
    async def emit_second(kind: str, payload: dict) -> None: second.append((kind,payload))
    await handle_create(cmd.model_dump_json().encode(), service, emit_first)
    await handle_create(cmd.model_dump_json().encode(), service, emit_second)
    assert len(service.events(cmd.tenant_id, cmd.investigation_id)) == 3
    assert [item[1]["sequence_number"] for item in second] == [1,2,3]


@pytest.mark.asyncio
async def test_cancel_worker_emits_ordered_terminal_events(tmp_path) -> None:
    service = InvestigationService(SqlAlchemyInvestigationRepository(f"sqlite:///{tmp_path / 'cancel-worker.db'}", create_schema=True))
    cmd = CreateInvestigationCommand(investigation_id=uuid4(), tenant_id=uuid4(), requested_by=uuid4(), idempotency_key="worker-investigation-cancel", query="Why did payment latency increase after deployment?")
    async def discard(kind: str, payload: dict) -> None: return None
    await handle_create(cmd.model_dump_json().encode(), service, discard)
    emitted: list[tuple[str,dict]]=[]
    async def emit(kind: str,payload: dict)->None: emitted.append((kind,payload))
    cancel=CancelInvestigationCommand(investigation_id=cmd.investigation_id,tenant_id=cmd.tenant_id,requested_by=cmd.requested_by,correlation_id=cmd.correlation_id,reason="Stop investigation")
    await handle_cancel(cancel.model_dump_json().encode(),service,emit)
    assert [kind for kind,_ in emitted] == ["investigation.status.changed","investigation.cancelled"]
    assert emitted[-1][1]["sequence_number"] == 5


@pytest.mark.asyncio
async def test_worker_rejects_invalid_create_contract(tmp_path) -> None:
    service = InvestigationService(SqlAlchemyInvestigationRepository(f"sqlite:///{tmp_path / 'invalid.db'}", create_schema=True))
    events=[]
    async def emit(kind: str,payload: dict)->None: events.append(kind)
    await handle_create(json.dumps({"query":"short"}).encode(),service,emit)
    assert events == ["investigation.command.rejected"]
