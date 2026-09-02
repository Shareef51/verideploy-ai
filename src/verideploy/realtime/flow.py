from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterable

@dataclass(frozen=True)
class FlowStage:
    name: str
    required: bool = True

@dataclass(frozen=True)
class ReconciliationResult:
    applied_sequences: tuple[int, ...]
    duplicate_sequences: tuple[int, ...]
    missing_sequences: tuple[int, ...]
    high_watermark: int
    converged: bool

RELEASE_FLOW = (
    FlowStage("browser.command"), FlowStage("nestjs.validation"), FlowStage("kafka.command"),
    FlowStage("worker.consume"), FlowStage("langgraph.release_risk"), FlowStage("persistence"),
    FlowStage("kafka.event"), FlowStage("redis.websocket"), FlowStage("browser.reconcile"),
)
INCIDENT_FLOW = (
    FlowStage("browser.command"), FlowStage("nestjs.validation"), FlowStage("kafka.command"),
    FlowStage("worker.consume"), FlowStage("langgraph.incident_rca"), FlowStage("citations"),
    FlowStage("audit"), FlowStage("persistence"), FlowStage("kafka.event"),
    FlowStage("redis.websocket"), FlowStage("browser.reconcile"),
)

def reconcile_event_stream(events: Iterable[dict[str, Any]], *, authoritative_high_watermark: int) -> ReconciliationResult:
    seen: set[int] = set(); duplicates: list[int] = []
    for event in events:
        seq = int(event["sequence_number"])
        if seq in seen: duplicates.append(seq)
        else: seen.add(seq)
    applied = tuple(sorted(s for s in seen if 1 <= s <= authoritative_high_watermark))
    missing = tuple(s for s in range(1, authoritative_high_watermark + 1) if s not in seen)
    return ReconciliationResult(applied, tuple(sorted(duplicates)), missing, authoritative_high_watermark, not missing and applied == tuple(range(1, authoritative_high_watermark + 1)))

def validate_terminal_flow(*, workflow: str, stages: Iterable[str], status: str, citations: Iterable[str], audit_events: int, ui_status: str) -> list[str]:
    required = RELEASE_FLOW if workflow == "release_risk" else INCIDENT_FLOW
    present = set(stages); errors = [f"missing stage: {stage.name}" for stage in required if stage.required and stage.name not in present]
    if status != "COMPLETED": errors.append("authoritative status must be COMPLETED")
    if ui_status != status: errors.append("final UI must match authoritative status")
    if not tuple(citations): errors.append("terminal result must contain citations")
    if audit_events < 1: errors.append("terminal flow must contain an audit event")
    return errors
