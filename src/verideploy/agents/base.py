from __future__ import annotations

from typing import Generic, TypeVar
from pydantic import BaseModel

from .contracts import AgentAuthorization, AgentName, AgentRequest, ToolBudget
from .model import AgentContract, AgentModelPort
from .prompts import PromptRegistry
from .repository import AgentRunRepository

T = TypeVar("T", bound=BaseModel)


class BaseAgent(Generic[T]):
    agent_name: AgentName
    prompt_name: str
    prompt_version = "1.0.0"
    agent_version = "1.0.0"
    schema_version = "1.0.0"
    schema_migrations: tuple[tuple[str, str], ...] = ()
    model_name = "role:standard"
    reasoning_setting = "standard"
    output_model: type[T]
    schema_name: str

    def __init__(self, *, model: AgentModelPort, prompts: PromptRegistry, repository: AgentRunRepository) -> None:
        self.model=model; self.prompts=prompts; self.repository=repository

    async def _generate(self, request: AgentRequest, *, authorization: AgentAuthorization, budget: ToolBudget, payload: dict) -> tuple[T, object]:
        if request.tenant_id != authorization.tenant_id or request.user_id != authorization.user_id:
            raise PermissionError("agent authorization context does not match request identity")
        prompt=self.prompts.get(self.prompt_name, self.prompt_version)
        run=self.repository.start(tenant_id=request.tenant_id, agent_name=self.agent_name, prompt_name=prompt.name, prompt_version=prompt.version, prompt_sha256=prompt.sha256, payload=payload, max_tool_calls=budget.max_calls)
        try:
            contract = AgentContract(self.agent_version, prompt.version, self.schema_version, self.schema_migrations)
            output=await self.model.generate(tenant_id=request.tenant_id, correlation_id=request.correlation_id, operation=f"agent.{self.agent_name.value}", prompt=prompt.text, payload=payload, output_model=self.output_model, schema_name=self.schema_name, prompt_name=prompt.name, prompt_version=contract.prompt_version, prompt_sha256=prompt.sha256, schema_version=contract.schema_version, agent_version=contract.agent_version, graph_version=str(request.context.get("graph_version", "standalone")), model=self.model_name, reasoning_setting=self.reasoning_setting)
            return output, run
        except Exception as exc:
            self.repository.fail(tenant_id=request.tenant_id, run_id=run.run_id, error_code=type(exc).__name__, tool_calls_used=budget.calls_used)
            raise
