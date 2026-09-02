from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from verideploy.approvals.repository import ApprovalConflictError, ApprovalRepository
from verideploy.approvals.schemas import (
    ACTIVE_STATUSES, ApprovalAuthorization, ApprovalDecision, ApprovalEvent, ApprovalEventType,
    ApprovalRequest, ApprovalRequestCreate, ApprovalStatus, DecisionCommand, DelegationCommand, ReviewerContext,
)
from verideploy.approvals.signing import ApprovalAuditSigner


class ApprovalPermissionError(PermissionError):
    pass


class ApprovalExpiredError(RuntimeError):
    pass


class HumanApprovalService:
    def __init__(self, *, repository: ApprovalRepository, signer: ApprovalAuditSigner) -> None:
        self.repository = repository
        self.signer = signer

    def _event(self, *, request: ApprovalRequest, event_type: ApprovalEventType, actor_id: str, actor_role: str | None,
               payload: dict, previous_status: ApprovalStatus | None, new_status: ApprovalStatus | None, sequence: int) -> ApprovalEvent:
        occurred_at = datetime.now(timezone.utc)
        signed = {
            "approval_id": str(request.approval_id), "tenant_id": str(request.tenant_id), "sequence": sequence,
            "event_type": event_type.value, "actor_id": actor_id, "actor_role": actor_role,
            "payload": payload, "previous_status": previous_status.value if previous_status else None,
            "new_status": new_status.value if new_status else None, "occurred_at": occurred_at.isoformat(),
        }
        digest, signature = self.signer.sign(signed)
        return ApprovalEvent(
            approval_id=request.approval_id, tenant_id=request.tenant_id, sequence=sequence, event_type=event_type,
            actor_id=actor_id, actor_role=actor_role, payload=payload, previous_status=previous_status,
            new_status=new_status, signed_payload_sha256=digest, signature=signature, occurred_at=occurred_at,
        )

    def request_review(self, payload: ApprovalRequestCreate) -> ApprovalRequest:
        if not payload.policy.requires_review(risk_score=payload.risk_score, risk=payload.risk):
            raise ValueError("review policy does not require human approval for this action")
        now = datetime.now(timezone.utc)
        request = ApprovalRequest(
            **payload.model_dump(), expires_at=now + timedelta(seconds=payload.policy.expiry_seconds),
            created_at=now, updated_at=now,
        )
        event = self._event(
            request=request, event_type=ApprovalEventType.CREATED, actor_id=payload.requested_by, actor_role="requester",
            payload={"action_type": payload.action_type, "risk": payload.risk.value, "risk_score": payload.risk_score,
                     "expires_at": request.expires_at.isoformat(), "evidence_summary": payload.evidence_summary.model_dump(mode="json")},
            previous_status=None, new_status=ApprovalStatus.PENDING, sequence=1,
        )
        return self.repository.create_or_get(request, event)

    @staticmethod
    def _authorize_reviewer(request: ApprovalRequest, reviewer: ReviewerContext) -> None:
        if request.delegated_to is not None and request.delegated_to != reviewer.reviewer_id:
            raise ApprovalPermissionError("approval delegated to another reviewer")
        required = set(request.policy.required_roles)
        if required and not required.intersection(reviewer.roles):
            raise ApprovalPermissionError("reviewer lacks required role")

    def _expire_if_needed(self, request: ApprovalRequest, *, actor_id: str = "system") -> ApprovalRequest:
        if request.status not in ACTIVE_STATUSES or request.expires_at > datetime.now(timezone.utc):
            return request
        updated = request.model_copy(update={"status": ApprovalStatus.EXPIRED, "version": request.version + 1, "updated_at": datetime.now(timezone.utc)})
        event = self._event(request=request, event_type=ApprovalEventType.EXPIRED, actor_id=actor_id, actor_role="system", payload={},
                            previous_status=request.status, new_status=ApprovalStatus.EXPIRED,
                            sequence=len(self.repository.list_events(tenant_id=request.tenant_id, approval_id=request.approval_id)) + 1)
        try:
            return self.repository.transition(tenant_id=request.tenant_id, approval_id=request.approval_id, expected_version=request.version,
                                              allowed_statuses=ACTIVE_STATUSES, updated=updated, event=event)
        except ApprovalConflictError:
            current = self.repository.get(tenant_id=request.tenant_id, approval_id=request.approval_id)
            if current is None:
                raise
            return current

    def get(self, *, tenant_id: UUID, approval_id: UUID) -> ApprovalRequest | None:
        request = self.repository.get(tenant_id=tenant_id, approval_id=approval_id)
        return None if request is None else self._expire_if_needed(request)

    def queue(self, *, tenant_id: UUID, reviewer: ReviewerContext | None = None) -> list[ApprovalRequest]:
        items = self.repository.list_queue(tenant_id=tenant_id, reviewer_id=None if reviewer is None else reviewer.reviewer_id)
        active: list[ApprovalRequest] = []
        for item in items:
            item = self._expire_if_needed(item)
            if item.status in ACTIVE_STATUSES:
                if reviewer is None:
                    active.append(item)
                else:
                    try:
                        self._authorize_reviewer(item, reviewer)
                    except ApprovalPermissionError:
                        continue
                    active.append(item)
        return active

    def decide(self, command: DecisionCommand) -> ApprovalRequest:
        request = self.get(tenant_id=command.tenant_id, approval_id=command.approval_id)
        if request is None:
            raise KeyError("approval not found")
        if request.status not in ACTIVE_STATUSES:
            raise ApprovalConflictError("approval is already terminal")
        if request.expires_at <= datetime.now(timezone.utc):
            raise ApprovalExpiredError("approval expired")
        self._authorize_reviewer(request, command.reviewer)
        if command.decision == ApprovalDecision.REJECT and request.policy.require_comment_on_reject and not (command.comment or "").strip():
            raise ValueError("rejection comment required by review policy")
        status = {
            ApprovalDecision.APPROVE: ApprovalStatus.APPROVED,
            ApprovalDecision.REJECT: ApprovalStatus.REJECTED,
            ApprovalDecision.REQUEST_CHANGES: ApprovalStatus.CHANGES_REQUESTED,
        }[command.decision]
        event_type = {
            ApprovalDecision.APPROVE: ApprovalEventType.APPROVED,
            ApprovalDecision.REJECT: ApprovalEventType.REJECTED,
            ApprovalDecision.REQUEST_CHANGES: ApprovalEventType.CHANGES_REQUESTED,
        }[command.decision]
        now = datetime.now(timezone.utc)
        updated = request.model_copy(update={
            "status": status, "reviewer_id": command.reviewer.reviewer_id, "decision_comment": command.comment,
            "version": request.version + 1, "updated_at": now,
        })
        event = self._event(
            request=request, event_type=event_type, actor_id=command.reviewer.reviewer_id,
            actor_role=sorted(command.reviewer.roles)[0] if command.reviewer.roles else None,
            payload={"decision": command.decision.value, "comment": command.comment}, previous_status=request.status,
            new_status=status, sequence=len(self.repository.list_events(tenant_id=request.tenant_id, approval_id=request.approval_id)) + 1,
        )
        return self.repository.transition(
            tenant_id=request.tenant_id, approval_id=request.approval_id, expected_version=command.expected_version,
            allowed_statuses=ACTIVE_STATUSES, updated=updated, event=event,
        )

    def delegate(self, command: DelegationCommand) -> ApprovalRequest:
        request = self.get(tenant_id=command.tenant_id, approval_id=command.approval_id)
        if request is None:
            raise KeyError("approval not found")
        if not request.policy.allow_delegation:
            raise ApprovalPermissionError("review policy forbids delegation")
        self._authorize_reviewer(request, command.reviewer)
        now = datetime.now(timezone.utc)
        updated = request.model_copy(update={
            "status": ApprovalStatus.IN_REVIEW, "reviewer_id": command.reviewer.reviewer_id,
            "delegated_to": command.delegated_to, "version": request.version + 1, "updated_at": now,
        })
        event = self._event(
            request=request, event_type=ApprovalEventType.DELEGATED, actor_id=command.reviewer.reviewer_id,
            actor_role=sorted(command.reviewer.roles)[0] if command.reviewer.roles else None,
            payload={"delegated_to": command.delegated_to}, previous_status=request.status,
            new_status=ApprovalStatus.IN_REVIEW, sequence=len(self.repository.list_events(tenant_id=request.tenant_id, approval_id=request.approval_id)) + 1,
        )
        return self.repository.transition(tenant_id=request.tenant_id, approval_id=request.approval_id, expected_version=command.expected_version,
                                          allowed_statuses=ACTIVE_STATUSES, updated=updated, event=event)

    def authorize_action(self, *, tenant_id: UUID, approval_id: UUID) -> ApprovalAuthorization:
        request = self.get(tenant_id=tenant_id, approval_id=approval_id)
        if request is None:
            return ApprovalAuthorization(approval_id=approval_id, authorized=False, reason="approval_not_found", version=0)
        if request.status == ApprovalStatus.APPROVED:
            return ApprovalAuthorization(approval_id=approval_id, authorized=True, reason="approved", version=request.version)
        return ApprovalAuthorization(approval_id=approval_id, authorized=False, reason=f"approval_{request.status.value}", version=request.version)

    def events(self, *, tenant_id: UUID, approval_id: UUID) -> list[ApprovalEvent]:
        return self.repository.list_events(tenant_id=tenant_id, approval_id=approval_id)
