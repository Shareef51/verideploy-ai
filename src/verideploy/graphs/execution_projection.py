from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from verideploy.graphs.runtime import GraphRunRecord, GraphRuntimeEvent

_SENSITIVE_KEY = re.compile(r"(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|private[_-]?key|cookie)", re.I)


def sanitize_payload(value: Any, *, depth: int = 0) -> Any:
    """Remove credential-shaped values before an execution event reaches a browser."""
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            out[key_s] = "[REDACTED]" if _SENSITIVE_KEY.search(key_s) else sanitize_payload(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [sanitize_payload(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + "…"
    return value


class ExecutionNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    label: str
    status: Literal["pending", "running", "completed", "failed", "timed_out", "cancelled", "waiting_approval"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    retries: int = Field(default=0, ge=0)
    parent_node_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    last_sequence: int = Field(ge=0)


class ToolCallView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str
    node_id: str | None = None
    tool_name: str
    status: Literal["started", "completed", "failed"]
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    sequence_number: int = Field(ge=1)


class ModelCallView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str
    node_id: str | None = None
    model_role: str
    model_name: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    sequence_number: int = Field(ge=1)


class ExecutionEventView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    sequence_number: int
    event_type: str
    node_name: str | None
    occurred_at: datetime
    payload: dict[str, Any]


class AgentExecutionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    tenant_id: UUID
    thread_id: str
    graph_name: str
    graph_version: str
    status: str
    last_sequence: int
    nodes: list[ExecutionNode]
    tools: list[ToolCallView]
    models: list[ModelCallView]
    events: list[ExecutionEventView]
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    failure_count: int
    convergence_sha256: str


def _status_from_event(event_type: str, payload: dict[str, Any]) -> str | None:
    explicit = str(payload.get("status", "")).lower()
    if explicit in {"pending","running","completed","failed","timed_out","cancelled","waiting_approval"}:
        return explicit
    tail = event_type.rsplit(".", 1)[-1]
    return {"started":"running","completed":"completed","failed":"failed","timed_out":"timed_out","cancelled":"cancelled","interrupted":"waiting_approval"}.get(tail)


def _duration_ms(started: datetime | None, completed: datetime | None, payload: dict[str, Any]) -> int | None:
    supplied = payload.get("duration_ms")
    if isinstance(supplied, (int, float)) and supplied >= 0:
        return int(supplied)
    if started is not None and completed is not None:
        return max(0, int((completed - started).total_seconds() * 1000))
    return None


def projection_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def project_agent_execution(run: GraphRunRecord, events: list[GraphRuntimeEvent]) -> AgentExecutionProjection:
    ordered = sorted(events, key=lambda item: (item.sequence_number, str(item.event_id)))
    node_state: dict[str, dict[str, Any]] = {}
    tools: dict[str, ToolCallView] = {}
    models: dict[str, ModelCallView] = {}
    visible_events: list[ExecutionEventView] = []

    for event in ordered:
        payload = sanitize_payload(event.payload or {})
        visible_events.append(ExecutionEventView(event_id=event.event_id, sequence_number=event.sequence_number, event_type=event.event_type, node_name=event.node_name, occurred_at=event.occurred_at, payload=payload))
        node_id = event.node_name or (str(payload.get("node_id")) if payload.get("node_id") else None)
        if node_id and (event.event_type.startswith("graph.parallel.node.") or event.event_type.startswith("agent.node.") or payload.get("node_id")):
            state = node_state.setdefault(node_id, {"node_id":node_id,"label":str(payload.get("label") or node_id),"status":"pending","started_at":None,"completed_at":None,"retries":0,"parent_node_id":payload.get("parent_node_id"),"error_code":None,"error_message":None,"last_sequence":0})
            status = _status_from_event(event.event_type, payload)
            if status: state["status"] = status
            if status == "running" and state["started_at"] is None: state["started_at"] = event.occurred_at
            if status in {"completed","failed","timed_out","cancelled"}: state["completed_at"] = event.occurred_at
            if event.event_type.endswith("retry") or event.event_type.endswith("retried") or payload.get("retry") is True:
                state["retries"] += 1
            if isinstance(payload.get("retry_count"), int): state["retries"] = max(state["retries"], int(payload["retry_count"]))
            if status in {"failed","timed_out"}:
                state["error_code"] = str(payload.get("error_code")) if payload.get("error_code") else None
                msg = payload.get("error_message") or payload.get("reason")
                state["error_message"] = str(msg)[:2000] if msg else None
            state["last_sequence"] = event.sequence_number

        if event.event_type.startswith("agent.tool."):
            call_id = str(payload.get("call_id") or event.event_id)
            status = event.event_type.rsplit(".",1)[-1]
            if status not in {"started","completed","failed"}: status = "started"
            tool = ToolCallView(call_id=call_id,node_id=node_id,tool_name=str(payload.get("tool_name") or payload.get("tool") or "unknown"),status=status,arguments=sanitize_payload(payload.get("arguments") or {}),result_summary=(str(payload.get("result_summary"))[:2000] if payload.get("result_summary") else None),duration_ms=(int(payload["duration_ms"]) if isinstance(payload.get("duration_ms"),(int,float)) and payload["duration_ms"]>=0 else None),sequence_number=event.sequence_number)
            tools[call_id] = tool

        if event.event_type.startswith("agent.model."):
            call_id = str(payload.get("call_id") or event.event_id)
            role = str(payload.get("model_role") or "unknown")
            models[call_id] = ModelCallView(call_id=call_id,node_id=node_id,model_role=role,model_name=(str(payload.get("model_name")) if payload.get("model_name") else None),input_tokens=max(0,int(payload.get("input_tokens") or 0)),output_tokens=max(0,int(payload.get("output_tokens") or 0)),cost_usd=max(0.0,float(payload.get("cost_usd") or 0.0)),latency_ms=(max(0,int(payload["latency_ms"])) if isinstance(payload.get("latency_ms"),(int,float)) else None),sequence_number=event.sequence_number)

    nodes=[]
    for state in sorted(node_state.values(), key=lambda item: (item["last_sequence"], item["node_id"])):
        nodes.append(ExecutionNode(**state, duration_ms=_duration_ms(state["started_at"], state["completed_at"], {})))
    tool_list=sorted(tools.values(), key=lambda x:(x.sequence_number,x.call_id))
    model_list=sorted(models.values(), key=lambda x:(x.sequence_number,x.call_id))
    event_list=visible_events
    base={
        "run_id":run.run_id,"tenant_id":run.tenant_id,"thread_id":run.thread_id,"graph_name":run.graph_name,"graph_version":run.graph_version,
        "status":run.status.value,"last_sequence":run.last_sequence,"nodes":[x.model_dump(mode="json") for x in nodes],"tools":[x.model_dump(mode="json") for x in tool_list],"models":[x.model_dump(mode="json") for x in model_list],"events":[x.model_dump(mode="json") for x in event_list],
        "total_input_tokens":sum(x.input_tokens for x in model_list),"total_output_tokens":sum(x.output_tokens for x in model_list),"total_cost_usd":round(sum(x.cost_usd for x in model_list),8),"failure_count":sum(1 for x in nodes if x.status in {"failed","timed_out"}),
    }
    return AgentExecutionProjection(**base, convergence_sha256=projection_hash(base))
