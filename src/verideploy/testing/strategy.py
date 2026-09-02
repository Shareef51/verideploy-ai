from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

@dataclass(frozen=True)
class CoverageGate:
    measured_percent: float
    required_percent: float
    passed: bool

@dataclass(frozen=True)
class MutationResult:
    name: str
    killed: bool
    reason: str

def load_strategy(root: Path) -> dict:
    return json.loads((root / "config/testing/strategy.json").read_text())

def validate_suite_inventory(root: Path, strategy: dict) -> list[str]:
    errors: list[str] = []
    for name, paths in strategy["suites"].items():
        if not any((root / p).exists() for p in paths):
            errors.append(f"suite has no fixture path: {name}")
    for path in strategy["critical_modules"]:
        if not (root / path).exists():
            errors.append(f"missing critical module: {path}")
    return errors

def shard_for(nodeid: str, shard_count: int) -> int:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    import hashlib
    return int.from_bytes(hashlib.sha256(nodeid.encode()).digest()[:8], "big") % shard_count

def coverage_gate(measured: float, required: float) -> CoverageGate:
    return CoverageGate(measured, required, measured >= required)

def critical_mutation_probes() -> tuple[MutationResult, ...]:
    from verideploy.realtime.flow import reconcile_event_stream, validate_terminal_flow
    from verideploy.events.core import EventEnvelope, OrderedInbox, RetryPolicy

    # Mutant: treat a missing sequence as converged. The real implementation must reject it.
    r = reconcile_event_stream([{"sequence_number": 1}, {"sequence_number": 3}], authoritative_high_watermark=3)
    gap = MutationResult("reconciliation_gap_detection", not r.converged and r.missing_sequences == (2,), "gap must block convergence")

    # Mutant: re-apply duplicate Kafka event. Real inbox must suppress it.
    e = EventEnvelope(event_type="x", tenant_id="t", aggregate_id="a", ordering_key="t:a", sequence_number=1, payload={}, correlation_id="c", producer="p", schema_family="x")
    inbox=OrderedInbox(); applied=[]; first=inbox.accept(e, lambda item: applied.append(item.sequence_number)); second=inbox.accept(e, lambda item: applied.append(item.sequence_number))
    dedupe=MutationResult("ordered_inbox_deduplication", first.status=="applied" and second.status=="duplicate" and applied==[1], "duplicate must not reapply")

    # Mutant: retry forever instead of DLQ.
    decision=RetryPolicy(max_attempts=3).decide("base",3,"retry","dlq")
    dlq=MutationResult("retry_to_dlq", decision.terminal and decision.destination_topic=="dlq", "terminal retry must route to DLQ")

    # Mutant: allow terminal response without citations.
    errors=validate_terminal_flow(workflow="release_risk", stages=["browser.command","nestjs.validation","kafka.command","worker.consume","langgraph.release_risk","persistence","kafka.event","redis.websocket","browser.reconcile"], status="COMPLETED", citations=[], audit_events=1, ui_status="COMPLETED")
    cite=MutationResult("terminal_flow_citation_requirement", any("citations" in e for e in errors), "terminal result must require citations")
    return (gap,dedupe,dlq,cite)
