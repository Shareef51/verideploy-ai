from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from verideploy.llm.responses import (
    AIResponseInputItem,
    AIToolCall,
    AIToolChoice,
    AIToolDefinition,
    AIResponseStatus,
    AIJSONSchemaFormat,
)
from verideploy.llm.routing import ModelRole


class AIProviderName(StrEnum):
    OPENAI = "openai"
    TEST = "test"


class AIRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: str = Field(min_length=1, max_length=128)
    operation: str = Field(min_length=1, max_length=128)
    model_role: ModelRole | None = None
    model: str | None = Field(default=None, min_length=1, max_length=128)
    input: str | list[AIResponseInputItem]
    instructions: str | None = Field(default=None, max_length=50_000)
    max_output_tokens: int = Field(default=1024, ge=1, le=32_768)
    tools: list[AIToolDefinition] = Field(default_factory=list, max_length=64)
    tool_choice: AIToolChoice = "auto"
    previous_response_id: str | None = Field(default=None, min_length=1, max_length=256)
    store_provider_response: bool = False
    background: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)
    structured_output: AIJSONSchemaFormat | None = None
    defer_response_persistence: bool = False

    @model_validator(mode="after")
    def validate_input(self) -> "AIRequest":
        if isinstance(self.input, str):
            if not self.input.strip():
                raise ValueError("input must not be blank")
            if len(self.input) > 200_000:
                raise ValueError("input exceeds 200000 characters")
        elif not self.input:
            raise ValueError("input items must not be empty")
        return self


class AIUsage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)


class AIResult(BaseModel):
    request_id: UUID
    provider: AIProviderName
    model_role: ModelRole | None = None
    model: str
    route_reason: str | None = None
    output_text: str
    tool_calls: list[AIToolCall] = Field(default_factory=list)
    response_status: AIResponseStatus = AIResponseStatus.COMPLETED
    provider_response_id: str | None = None
    provider_request_id: str | None = None
    usage: AIUsage = Field(default_factory=AIUsage)
    estimated_cost_usd: str | None = None
    actual_cost_usd: str | None = None
    latency_ms: float = Field(ge=0)
    attempts: int = Field(ge=1)
    fallback_index: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
