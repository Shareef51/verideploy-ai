from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from verideploy.releases.schemas import (
    ReleaseRiskAssessment,
    ReleaseRiskPolicyInput,
    RiskDecision,
    RiskFactor,
    RiskLevel,
)

POLICY_VERSION = "release-risk-v1.0.0"


def _factor(code: str, label: str, points: int, value: object, rationale: str) -> RiskFactor:
    return RiskFactor(
        code=code,
        label=label,
        points=max(0, min(points, 100)),
        observed_value=str(value),
        rationale=rationale,
    )


def calculate_release_risk(
    *,
    assessment_id: UUID,
    release_id: str,
    policy: ReleaseRiskPolicyInput,
    human_review_threshold: int,
) -> ReleaseRiskAssessment:
    factors: list[RiskFactor] = []

    if policy.changed_services:
        factors.append(_factor("blast_radius", "Changed service blast radius", min(18, policy.changed_services * 3), policy.changed_services, "More independently deployed services increase coordinated release risk."))
    if policy.changed_files >= 50:
        factors.append(_factor("change_size", "Large change set", min(12, policy.changed_files // 25), policy.changed_files, "Large releases increase review surface and rollback complexity."))
    if policy.failed_workflows:
        factors.append(_factor("workflow_failures", "Failed CI workflows", min(30, policy.failed_workflows * 10), policy.failed_workflows, "Failed required workflows materially reduce release confidence."))
    if policy.database_migration_changed:
        factors.append(_factor("database_migration", "Database migration present", 18, True, "Schema changes can create backward-compatibility and rollback risk."))
    if policy.database_migration_changed and not policy.rollback_plan_verified:
        factors.append(_factor("migration_rollback", "Migration rollback not verified", 18, False, "An unverified database rollback path increases recovery risk."))
    elif not policy.rollback_plan_verified:
        factors.append(_factor("rollback_unverified", "Rollback plan not verified", 10, False, "Release rollback has not been operationally verified."))
    if policy.high_severity_incidents_last_30d:
        factors.append(_factor("recent_severe_incidents", "Recent high-severity incidents", min(20, policy.high_severity_incidents_last_30d * 7), policy.high_severity_incidents_last_30d, "Recent severe incidents indicate elevated change sensitivity."))
    elif policy.production_incidents_last_30d:
        factors.append(_factor("recent_incidents", "Recent production incidents", min(10, policy.production_incidents_last_30d * 2), policy.production_incidents_last_30d, "Recent incidents modestly raise the operational risk baseline."))
    if policy.test_coverage_delta_percent < 0:
        factors.append(_factor("coverage_drop", "Test coverage regression", min(12, int(abs(policy.test_coverage_delta_percent) * 1.5)), policy.test_coverage_delta_percent, "Reduced test coverage lowers automated change confidence."))
    if policy.security_scan_critical_findings:
        factors.append(_factor("critical_security", "Critical security findings", min(40, policy.security_scan_critical_findings * 20), policy.security_scan_critical_findings, "Known critical security findings are release-blocking signals."))
    if policy.deployment_window_risk:
        factors.append(_factor("deployment_window", "Deployment window risk", min(20, policy.deployment_window_risk), policy.deployment_window_risk, "Operational timing and staffing constraints increase response risk."))

    raw_score = sum(item.points for item in factors)
    score = min(raw_score, 100)
    if policy.security_scan_critical_findings > 0:
        score = max(score, 85)
    if policy.failed_workflows >= 2:
        score = max(score, 75)
    if policy.database_migration_changed and not policy.rollback_plan_verified:
        score = max(score, 80)

    if score >= 85:
        level, decision = RiskLevel.CRITICAL, RiskDecision.BLOCK
    elif score >= 70:
        level, decision = RiskLevel.HIGH, RiskDecision.DELAY
    elif score >= 35:
        level, decision = RiskLevel.MEDIUM, RiskDecision.PROCEED_WITH_GUARDRAILS
    else:
        level, decision = RiskLevel.LOW, RiskDecision.PROCEED

    primary = [f.label for f in sorted(factors, key=lambda item: item.points, reverse=True)[:5]]
    actions: list[str] = []
    factor_codes = {f.code for f in factors}
    if "workflow_failures" in factor_codes:
        actions.append("Resolve failed required workflows and rerun the release assessment.")
    if "database_migration" in factor_codes:
        actions.append("Verify migration compatibility against the current production schema.")
    if "migration_rollback" in factor_codes or "rollback_unverified" in factor_codes:
        actions.append("Exercise and record the rollback procedure before deployment.")
    if "critical_security" in factor_codes:
        actions.append("Resolve critical security findings before deployment approval.")
    if not actions and score >= 35:
        actions.append("Use a guarded rollout with enhanced telemetry and explicit rollback criteria.")
    if not actions:
        actions.append("Proceed under the standard release checklist and monitoring policy.")

    evidence_signals = len(factors)
    confidence = min(0.96, 0.68 + min(evidence_signals, 7) * 0.04)

    return ReleaseRiskAssessment(
        assessment_id=assessment_id,
        release_id=release_id,
        score=score,
        level=level,
        decision=decision,
        primary_risks=primary,
        recommended_actions=actions,
        confidence=round(confidence, 2),
        requires_human_review=score >= human_review_threshold,
        factors=sorted(factors, key=lambda item: (-item.points, item.code)),
        policy_version=POLICY_VERSION,
        calculated_at=datetime.now(UTC),
    )
