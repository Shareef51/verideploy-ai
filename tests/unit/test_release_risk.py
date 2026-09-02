from uuid import uuid4

from verideploy.releases.risk_engine import calculate_release_risk
from verideploy.releases.schemas import ReleaseRiskPolicyInput, RiskDecision, RiskLevel


def test_low_risk_release_can_proceed() -> None:
    result = calculate_release_risk(assessment_id=uuid4(), release_id="v1.2.3", policy=ReleaseRiskPolicyInput(changed_files=8, changed_services=1), human_review_threshold=80)
    assert result.level == RiskLevel.LOW
    assert result.decision == RiskDecision.PROCEED
    assert result.requires_human_review is False


def test_unverified_migration_forces_human_review() -> None:
    result = calculate_release_risk(assessment_id=uuid4(), release_id="v4.8.2", policy=ReleaseRiskPolicyInput(changed_files=80, changed_services=3, failed_workflows=1, database_migration_changed=True, rollback_plan_verified=False), human_review_threshold=80)
    assert result.score >= 80
    assert result.requires_human_review is True
    assert result.decision in {RiskDecision.DELAY, RiskDecision.BLOCK}


def test_critical_security_finding_blocks_release() -> None:
    result = calculate_release_risk(assessment_id=uuid4(), release_id="v9", policy=ReleaseRiskPolicyInput(changed_files=2, changed_services=1, security_scan_critical_findings=1), human_review_threshold=80)
    assert result.score >= 85
    assert result.level == RiskLevel.CRITICAL
    assert result.decision == RiskDecision.BLOCK
