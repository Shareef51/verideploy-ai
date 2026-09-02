import json
from uuid import uuid4

import pytest

from verideploy.releases.repository import SqlAlchemyReleaseRiskRepository
from verideploy.releases.schemas import ReleaseRiskCommand, ReleaseRiskPolicyInput
from verideploy.releases.service import ReleaseRiskService
from workers.investigation.release_risk_worker import handle_release_risk_command


@pytest.mark.asyncio
async def test_worker_emits_started_then_completed(tmp_path) -> None:
    repo = SqlAlchemyReleaseRiskRepository(f"sqlite:///{tmp_path / 'worker.db'}", create_schema=True)
    service = ReleaseRiskService(repo)
    events: list[tuple[str, dict]] = []
    async def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))
    command = ReleaseRiskCommand(assessment_id=uuid4(), tenant_id=uuid4(), requested_by=uuid4(), idempotency_key="worker-risk-001", repository="nexuspay/payment-service", release_id="v4.8.2", commit_sha="abcdef1234", policy=ReleaseRiskPolicyInput(changed_files=10, changed_services=1))
    await handle_release_risk_command(command.model_dump_json().encode(), service, emit)
    assert [event[0] for event in events] == ["release.risk.started", "release.risk.completed"]
    assert events[-1][1]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_worker_rejects_invalid_contract(tmp_path) -> None:
    repo = SqlAlchemyReleaseRiskRepository(f"sqlite:///{tmp_path / 'worker-invalid.db'}", create_schema=True)
    service = ReleaseRiskService(repo)
    events: list[str] = []
    async def emit(event_type: str, payload: dict) -> None:
        events.append(event_type)
    await handle_release_risk_command(json.dumps({"release_id": "bad"}).encode(), service, emit)
    assert events == ["release.risk.command.rejected"]
