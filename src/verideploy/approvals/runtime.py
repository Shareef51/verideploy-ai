from __future__ import annotations

from uuid import UUID

from verideploy.approvals.schemas import ApprovalRequestCreate, ApprovalStatus
from verideploy.approvals.service import HumanApprovalService
from verideploy.graphs.runtime import GraphRunStatus, LangGraphRuntime


class ApprovalRuntimeBridge:
    """Durable Human in the Loop Approval interrupt/resume boundary around LangGraphRuntime."""

    def __init__(self, *, runtime: LangGraphRuntime, approvals: HumanApprovalService) -> None:
        self.runtime = runtime
        self.approvals = approvals

    def interrupt_for_review(self, payload: ApprovalRequestCreate):
        request = self.approvals.request_review(payload)
        run = self.runtime.repository.get_run(tenant_id=payload.tenant_id, run_id=payload.run_id)
        if run is None:
            raise KeyError("graph run not found")
        self.runtime.repository.set_status(tenant_id=payload.tenant_id, run_id=payload.run_id, status=GraphRunStatus.WAITING_FOR_APPROVAL)
        self.runtime.repository.append_event(
            tenant_id=payload.tenant_id, run_id=payload.run_id, thread_id=run.thread_id,
            graph_name=run.graph_name, graph_version=run.graph_version, event_type="graph.approval.interrupted",
            payload={"approval_id": str(request.approval_id), "risk": request.risk.value, "risk_score": request.risk_score,
                     "expires_at": request.expires_at.isoformat()},
        )
        return request

    async def resume_approved(
        self, *, tenant_id: UUID, approval_id: UUID, correlation_id: str, graph_name: str, graph_version: str,
        input_state: dict, run_id: UUID, thread_id: str | None = None, timeout_seconds: float = 300.0,
    ):
        return await self.resume_reviewed(tenant_id=tenant_id,approval_id=approval_id,correlation_id=correlation_id,graph_name=graph_name,graph_version=graph_version,input_state=input_state,run_id=run_id,thread_id=thread_id,timeout_seconds=timeout_seconds,require_approved=True)

    async def resume_reviewed(
        self, *, tenant_id: UUID, approval_id: UUID, correlation_id: str, graph_name: str, graph_version: str,
        input_state: dict, run_id: UUID, thread_id: str | None = None, timeout_seconds: float = 300.0,
        require_approved: bool = False,
    ):
        approval = self.approvals.get(tenant_id=tenant_id, approval_id=approval_id)
        if approval is None:
            raise KeyError("approval not found")
        if approval.run_id != run_id:
            raise PermissionError("approval does not belong to graph run")
        if require_approved and approval.status != ApprovalStatus.APPROVED:
            raise PermissionError(f"graph resume requires approved review, got {approval.status.value}")
        if approval.status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise PermissionError(f"graph resume requires terminal approve/reject review, got {approval.status.value}")
        run = self.runtime.repository.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            raise KeyError("graph run not found")
        self.runtime.repository.append_event(
            tenant_id=tenant_id, run_id=run_id, thread_id=run.thread_id, graph_name=run.graph_name,
            graph_version=run.graph_version, event_type="graph.approval.resume.authorized",
            payload={"approval_id": str(approval_id), "approval_version": approval.version},
        )
        return await self.runtime.execute(
            tenant_id=tenant_id, correlation_id=correlation_id, graph_name=graph_name, graph_version=graph_version,
            input_state=input_state, run_id=run_id, thread_id=thread_id or run.thread_id, timeout_seconds=timeout_seconds,
            resume_value={"decision":"approve" if approval.status == ApprovalStatus.APPROVED else "reject","approval_id":str(approval_id),"approval_version":approval.version,"reviewer_id":approval.reviewer_id,"comment":approval.decision_comment},
        )
