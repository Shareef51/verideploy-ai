from __future__ import annotations

from uuid import UUID

from verideploy.releases.repository import ReleaseRiskRepository
from verideploy.releases.risk_engine import calculate_release_risk
from verideploy.releases.schemas import ReleaseRiskCommand, ReleaseRiskRecord, ReleaseRiskStatus
from verideploy.releases.schemas import ReleaseRiskAssessment


class ReleaseRiskService:
    def __init__(self, repository: ReleaseRiskRepository, human_review_threshold: int = 80) -> None:
        self._repository = repository
        self._human_review_threshold = human_review_threshold

    def accept(self, command: ReleaseRiskCommand) -> tuple[ReleaseRiskRecord, bool]:
        return self._repository.create_or_get(command)

    def assess(self, tenant_id: UUID, assessment_id: UUID) -> ReleaseRiskRecord:
        record = self._repository.get(tenant_id, assessment_id)
        if record is None:
            raise KeyError(str(assessment_id))
        if record.status == ReleaseRiskStatus.COMPLETED:
            return record
        self._repository.transition(tenant_id, assessment_id, ReleaseRiskStatus.RUNNING)
        try:
            result = calculate_release_risk(
                assessment_id=assessment_id,
                release_id=record.release_id,
                policy=record.policy_input,
                human_review_threshold=self._human_review_threshold,
            )
            return self._repository.transition(tenant_id, assessment_id, ReleaseRiskStatus.COMPLETED, result_json=result.model_dump_json())
        except Exception as exc:
            self._repository.transition(tenant_id, assessment_id, ReleaseRiskStatus.FAILED, error_code="RISK_CALCULATION_FAILED", error_message="Release risk calculation failed")
            raise RuntimeError("release risk calculation failed") from exc

    def complete_from_graph(self, tenant_id: UUID, assessment_id: UUID, output: dict) -> ReleaseRiskRecord:
        """Persist a validated graph result without recalculating it outside LangGraph."""
        result = ReleaseRiskAssessment.model_validate(output)
        return self._repository.transition(
            tenant_id, assessment_id, ReleaseRiskStatus.COMPLETED,
            result_json=result.model_dump_json(),
        )

    def get(self, tenant_id: UUID, assessment_id: UUID) -> ReleaseRiskRecord | None:
        return self._repository.get(tenant_id, assessment_id)

    def list_recent(self, tenant_id: UUID, limit: int = 50) -> list[ReleaseRiskRecord]:
        return self._repository.list_recent(tenant_id, limit)
