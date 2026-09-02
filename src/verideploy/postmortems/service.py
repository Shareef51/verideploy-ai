from __future__ import annotations

import json
from uuid import UUID

from verideploy.investigations.schemas import InvestigationStatus
from verideploy.investigations.service import InvestigationService
from verideploy.postmortems.repository import PostmortemRepository
from verideploy.postmortems.schemas import CreatePostmortemCommand, PostmortemExport, PostmortemRecord, PostmortemStatus, ReviewPostmortemCommand


class PostmortemEligibilityError(ValueError):
    """Raised when a postmortem source is not eligible for final generation."""


class PostmortemService:
    def __init__(self, repository: PostmortemRepository, investigations: InvestigationService) -> None:
        self._repository = repository; self._investigations = investigations

    def create(self, command: CreatePostmortemCommand) -> tuple[PostmortemRecord, bool]:
        investigation = self._investigations.get(command.tenant_id, command.investigation_id)
        if investigation is None:
            raise KeyError(str(command.investigation_id))
        if investigation.status is not InvestigationStatus.COMPLETED:
            raise PostmortemEligibilityError("source investigation must be COMPLETED before postmortem generation")
        if command.reviewed_evidence.reviewed_at < investigation.created_at:
            raise PostmortemEligibilityError("evidence review timestamp predates the investigation")
        return self._repository.create_or_get(command, investigation.version)

    def get(self, tenant_id: UUID, postmortem_id: UUID) -> PostmortemRecord | None:
        return self._repository.get(tenant_id, postmortem_id)

    def list(self, tenant_id: UUID, limit: int = 50) -> list[PostmortemRecord]:
        return self._repository.list(tenant_id, limit)

    def review(self, command: ReviewPostmortemCommand) -> PostmortemRecord:
        return self._repository.review(command)

    def export(self, tenant_id: UUID, postmortem_id: UUID, format_: str) -> PostmortemExport:
        record = self.get(tenant_id, postmortem_id)
        if record is None:
            raise KeyError(str(postmortem_id))
        if record.status is not PostmortemStatus.APPROVED:
            raise PostmortemEligibilityError("only APPROVED postmortems can be exported as final")
        if format_ == "json":
            return PostmortemExport(postmortem_id=postmortem_id, content_type="application/json", filename=f"postmortem-{postmortem_id}.json", content=json.dumps(record.model_dump(mode="json"), indent=2))
        if format_ != "markdown":
            raise ValueError("format must be markdown or json")
        lines = [f"# {record.title}", "", f"Status: {record.status.value}", f"Confidence: {record.confidence:.2f}", "", "## Root cause", record.root_cause, "", "## Impact", record.impact, "", "## Timeline"]
        for item in record.timeline:
            lines.append(f"- {item.occurred_at.isoformat()} — {item.summary} [{', '.join(item.evidence_ids)}]")
        lines += ["", "## Contributing factors", *[f"- {v}" for v in record.contributing_factors], "", "## Remediation", *[f"- {v}" for v in record.remediation_actions], "", "## Prevention", *[f"- {v}" for v in record.prevention_actions], "", "## Citations"]
        lines += [f"- {c.claim} [{', '.join(c.evidence_ids)}]" for c in record.citations]
        if record.limitations:
            lines += ["", "## Limitations", *[f"- {v}" for v in record.limitations]]
        return PostmortemExport(postmortem_id=postmortem_id, content_type="text/markdown", filename=f"postmortem-{postmortem_id}.md", content="\n".join(lines) + "\n")
