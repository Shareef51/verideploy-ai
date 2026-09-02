from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIInputText(BaseModel):
    type: Literal["input_text"] = "input_text"
    text: str = Field(min_length=1, max_length=200_000)


class AIInputImage(BaseModel):
    type: Literal["input_image"] = "input_image"
    image_url: str | None = Field(default=None, min_length=1, max_length=40_000_000)
    file_id: str | None = Field(default=None, min_length=1, max_length=256)
    detail: Literal["low", "high", "original", "auto"] = "auto"

    @model_validator(mode="after")
    def exactly_one_source(self) -> "AIInputImage":
        if (self.image_url is None) == (self.file_id is None):
            raise ValueError("input_image requires exactly one of image_url or file_id")
        if self.image_url is not None and not self.image_url.startswith("data:image/"):
            raise ValueError("VeriDeploy image inputs accept only sanitized data URLs")
        return self


AIMessageContentPart = Annotated[AIInputText | AIInputImage, Field(discriminator="type")]


class AIMessageInput(BaseModel):
    type: Literal["message"] = "message"
    role: Literal["user", "assistant", "system", "developer"]
    content: str | list[AIMessageContentPart]

    @model_validator(mode="after")
    def validate_content(self) -> "AIMessageInput":
        if isinstance(self.content, str):
            if not self.content.strip():
                raise ValueError("message content must not be blank")
            if len(self.content) > 200_000:
                raise ValueError("message content exceeds 200000 characters")
        elif not self.content:
            raise ValueError("message content parts must not be empty")
        return self


class AIFunctionCallOutput(BaseModel):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str = Field(min_length=1, max_length=256)
    output: str = Field(max_length=200_000)


AIResponseInputItem = AIMessageInput | AIFunctionCallOutput




class AIJSONSchemaFormat(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: Literal["json_schema"] = "json_schema"
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1024)
    schema_: dict[str, Any] = Field(alias="schema")
    strict: bool = True

class AIToolDefinition(BaseModel):
    type: Literal["function"] = "function"
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2048)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    strict: bool = True


class AIFunctionToolChoice(BaseModel):
    type: Literal["function"] = "function"
    name: str = Field(min_length=1, max_length=64)


AIToolChoice = Literal["auto", "none", "required"] | AIFunctionToolChoice


class AIToolCall(BaseModel):
    call_id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=64)
    arguments_json: str = Field(default="{}", max_length=200_000)


class AIResponseStatus(StrEnum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"
    UNKNOWN = "unknown"


class AIStreamEventType(StrEnum):
    RESPONSE_CREATED = "response.created"
    OUTPUT_TEXT_DELTA = "response.output_text.delta"
    TOOL_CALL_ADDED = "response.tool_call.added"
    TOOL_CALL_ARGUMENTS_DELTA = "response.tool_call_arguments.delta"
    RESPONSE_COMPLETED = "response.completed"
    RESPONSE_INCOMPLETE = "response.incomplete"
    RESPONSE_FAILED = "response.failed"
    RESPONSE_CANCELLED = "response.cancelled"


class AIStreamEvent(BaseModel):
    type: AIStreamEventType
    sequence_number: int = Field(ge=0)
    request_id: str
    provider_response_id: str | None = None
    delta: str | None = None
    tool_call: AIToolCall | None = None
    final_result: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def terminal_event_has_result(self) -> "AIStreamEvent":
        terminal = {
            AIStreamEventType.RESPONSE_COMPLETED,
            AIStreamEventType.RESPONSE_INCOMPLETE,
            AIStreamEventType.RESPONSE_CANCELLED,
        }
        if self.type in terminal and self.final_result is None:
            raise ValueError("terminal stream event requires final_result")
        return self
