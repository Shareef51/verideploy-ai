from __future__ import annotations

from verideploy.config import get_settings
from verideploy.llm.structured_output import StructuredOutputEngine
from verideploy.llm.structured_schemas import build_builtin_structured_registry

from .model import StructuredAgentModel
from .prompts import build_prompt_registry
from .repository import SqlAlchemyAgentRunRepository


def create_agent_runtime_components(*, gateway):
    settings = get_settings()
    registry = build_builtin_structured_registry()
    model = StructuredAgentModel(StructuredOutputEngine(registry=registry, gateway=gateway))
    prompts = build_prompt_registry()
    repository = SqlAlchemyAgentRunRepository(settings.database_url, create_schema=settings.app_env == "test")
    return model, prompts, repository
