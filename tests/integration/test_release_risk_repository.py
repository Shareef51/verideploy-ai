from uuid import uuid4

from verideploy.releases.repository import SqlAlchemyReleaseRiskRepository
from verideploy.releases.schemas import ReleaseRiskCommand, ReleaseRiskPolicyInput, ReleaseRiskStatus
from verideploy.releases.service import ReleaseRiskService


def command(key: str = "release-risk-key-001") -> ReleaseRiskCommand:
    return ReleaseRiskCommand(assessment_id=uuid4(), tenant_id=uuid4(), requested_by=uuid4(), idempotency_key=key, repository="nexuspay/payment-service", release_id="v4.8.2", commit_sha="a1b2c3d4", policy=ReleaseRiskPolicyInput(changed_files=40, changed_services=2))


def test_idempotent_assessment_and_persistence(tmp_path) -> None:
    repo = SqlAlchemyReleaseRiskRepository(f"sqlite:///{tmp_path / 'risk.db'}", create_schema=True)
    service = ReleaseRiskService(repo)
    cmd = command()
    first, created = service.accept(cmd)
    duplicate, duplicate_created = service.accept(cmd)
    assert created is True and duplicate_created is False
    assert first.assessment_id == duplicate.assessment_id
    completed = service.assess(first.tenant_id, first.assessment_id)
    assert completed.status == ReleaseRiskStatus.COMPLETED
    assert completed.result is not None
    restored = service.get(first.tenant_id, first.assessment_id)
    assert restored is not None and restored.result is not None
