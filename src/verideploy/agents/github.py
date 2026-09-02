from __future__ import annotations
from typing import Any, Protocol

from .base import BaseAgent
from .contracts import AgentAuthorization, AgentName, AgentRequest, GitHubAgentResult, GitHubFinding, GitHubToolPlan, ToolBudget


class GitHubToolPort(Protocol):
    async def invoke(self, operation: str, arguments: dict[str, str]) -> dict[str, Any]: ...


class GitHubAgent(BaseAgent[GitHubToolPlan]):
    model_name="role:fast"; reasoning_setting="low"
    agent_name=AgentName.GITHUB; prompt_name="github"; output_model=GitHubToolPlan; schema_name="github_tool_plan"

    def __init__(self, *, model, prompts, repository, tools: GitHubToolPort) -> None:
        super().__init__(model=model, prompts=prompts, repository=repository); self.tools=tools

    async def run(self, request: AgentRequest, *, authorization: AgentAuthorization, budget: ToolBudget) -> GitHubAgentResult:
        plan, run=await self._generate(request, authorization=authorization, budget=budget, payload={"objective": request.objective, "context": request.context, "allowed_permissions": sorted(p.value for p in authorization.allowed_permissions), "remaining_tool_calls": budget.remaining})
        if len(plan.calls) > budget.remaining:
            self.repository.fail(tenant_id=request.tenant_id, run_id=run.run_id, error_code="ToolBudgetExceeded", tool_calls_used=budget.calls_used); raise RuntimeError("github tool plan exceeds remaining budget")
        working=budget; findings=[]
        try:
            for call in plan.calls:
                authorization.require([call.permission]); working=working.consume()
                result=await self.tools.invoke(call.operation, call.arguments)
                summary=str(result.get("summary") or result.get("name") or result.get("status") or "GitHub read completed")
                findings.append(GitHubFinding(statement=summary[:4000], source_call_ids=[call.call_id]))
            output=GitHubAgentResult(summary=plan.rationale, findings=findings, tool_calls_used=working.calls_used)
            self.repository.complete(tenant_id=request.tenant_id, run_id=run.run_id, output=output.model_dump(mode="json"), tool_calls_used=working.calls_used)
            return output
        except Exception as exc:
            self.repository.fail(tenant_id=request.tenant_id, run_id=run.run_id, error_code=type(exc).__name__, tool_calls_used=working.calls_used); raise
