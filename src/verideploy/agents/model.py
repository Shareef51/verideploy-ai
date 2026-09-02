from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel

from verideploy.llm.contracts import AIRequest
from verideploy.llm.routing import ModelRole
from verideploy.llm.structured_output import StructuredOutputEngine

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class AgentContract:
    agent_version: str
    prompt_version: str
    schema_version: str
    migrations: tuple[tuple[str, str], ...] = ()


class AgentModelPort(Protocol):
    async def generate(self, *, tenant_id: UUID, correlation_id: str, operation: str, prompt: str, payload: dict, output_model: type[T], schema_name: str, prompt_name: str, prompt_version: str, prompt_sha256: str, schema_version: str, agent_version: str, graph_version: str, model: str, reasoning_setting: str) -> T: ...


class StructuredAgentModel:
    def __init__(self, engine: StructuredOutputEngine) -> None:
        self.engine = engine

    async def generate(self, *, tenant_id: UUID, correlation_id: str, operation: str, prompt: str, payload: dict, output_model: type[T], schema_name: str, prompt_name: str, prompt_version: str, prompt_sha256: str, schema_version: str, agent_version: str, graph_version: str, model: str, reasoning_setting: str) -> T:
        self.engine.ensure_schema(name=schema_name, version=schema_version, model=output_model)
        _, parsed, _ = await self.engine.execute(
            AIRequest(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                operation=operation,
                model_role=ModelRole(model.split(":",1)[1]) if model.startswith("role:") else None,
                model=None if model.startswith("role:") else model,
                input=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                instructions=prompt,
                max_output_tokens=4096,
                metadata={"prompt_name": prompt_name, "prompt_version": prompt_version, "prompt_sha256": prompt_sha256, "schema_name": schema_name, "schema_version": schema_version, "agent_version": agent_version, "graph_version": graph_version, "model": model, "reasoning_setting": reasoning_setting},
            ),
            schema_name=schema_name,
            schema_version=schema_version,
        )
        return output_model.model_validate(parsed.model_dump())
