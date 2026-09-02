from __future__ import annotations
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

class LLMOpsKind(StrEnum):
    MODEL_CALL='model_call'; TOOL_CALL='tool_call'; RETRIEVAL='retrieval'; AGENT='agent'; RETRY='retry'; FAILURE='failure'; CONFIDENCE='confidence'

class LLMOpsEvent(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event_id: UUID=Field(default_factory=uuid4)
    tenant_id: UUID
    correlation_id: str=Field(min_length=1,max_length=128)
    investigation_id: UUID|None=None
    graph_run_id: UUID|None=None
    agent_run_id: UUID|None=None
    retrieval_run_id: UUID|None=None
    tool_invocation_id: UUID|None=None
    kind: LLMOpsKind
    operation: str=Field(min_length=1,max_length=160)
    prompt_name: str|None=None
    prompt_version: str|None=None
    prompt_sha256: str|None=None
    model_role: str|None=None
    model_name: str|None=None
    input_tokens: int=Field(default=0,ge=0)
    output_tokens: int=Field(default=0,ge=0)
    total_tokens: int=Field(default=0,ge=0)
    latency_ms: float=Field(default=0,ge=0)
    cost_usd: float=Field(default=0,ge=0)
    tool_name: str|None=None
    retrieval_count: int=Field(default=0,ge=0)
    retry_count: int=Field(default=0,ge=0)
    failure_code: str|None=None
    confidence: float|None=Field(default=None,ge=0,le=1)
    payload: dict[str,Any]=Field(default_factory=dict)
    retention_class: str='operational_90d'
    occurred_at: datetime=Field(default_factory=lambda:datetime.now(timezone.utc))

class CorrelationTrace(BaseModel):
    tenant_id: UUID
    correlation_id: str
    events: list[LLMOpsEvent]
    model_calls: int
    tool_calls: int
    retrieval_calls: int
    retries: int
    failures: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost_usd: float
    total_latency_ms: float
    latest_confidence: float|None
