from .base import BaseAgent
from .contracts import AGENT_CAPABILITIES, AgentAuthorization, AgentName, AgentPlan, AgentRequest, ToolBudget
from .context import PLANNING_CONTEXT_KEYS, project_context

class PlanningAgent(BaseAgent[AgentPlan]):
    agent_name=AgentName.PLANNING; prompt_name="planner"; output_model=AgentPlan; schema_name="agent_plan"
    prompt_version="1.6.0"
    agent_version="2.1.0"; schema_version="2.0.0"; schema_migrations=(("1.0.0", "2.0.0"),)
    model_name="role:reasoning"; reasoning_setting="high"

    async def run(self, request: AgentRequest, *, authorization: AgentAuthorization, max_total_tool_calls: int = 12) -> AgentPlan:
        budget=ToolBudget(max_calls=max_total_tool_calls)
        output, run=await self._generate(request, authorization=authorization, budget=budget, payload={"objective":request.objective,"context":project_context(request.context,keys=PLANNING_CONTEXT_KEYS),"agent_contracts":AGENT_CAPABILITIES,"allowed_permissions":sorted(p.value for p in authorization.allowed_permissions),"max_total_tool_calls":max_total_tool_calls})
        try:
            total=sum(step.max_tool_calls for step in output.steps)
            if total > max_total_tool_calls:
                raise RuntimeError("plan exceeds total tool-call budget")
            for step in output.steps:
                authorization.require(step.required_permissions)
        except Exception as exc:
            self.repository.fail(tenant_id=request.tenant_id, run_id=run.run_id, error_code=type(exc).__name__, tool_calls_used=0)
            raise
        self.repository.complete(tenant_id=request.tenant_id, run_id=run.run_id, output=output.model_dump(mode="json"), tool_calls_used=0)
        return output
