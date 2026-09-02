from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ExplainPlanPolicy:
    max_execution_ms: float = 100.0
    max_total_cost: float = 25_000.0
    forbid_seq_scan_above_rows: int = 10_000


@dataclass(frozen=True, slots=True)
class ExplainPlanResult:
    accepted: bool
    execution_ms: float
    total_cost: float
    sequential_scans: tuple[tuple[str, int], ...]
    reasons: tuple[str, ...]


def _walk(node: dict[str, Any]):
    yield node
    for child in node.get('Plans', ()) or ():
        yield from _walk(child)


def evaluate_explain_plan(payload: list[dict[str, Any]], policy: ExplainPlanPolicy) -> ExplainPlanResult:
    if not payload or 'Plan' not in payload[0]:
        raise ValueError('EXPLAIN JSON payload must contain Plan')
    root = payload[0]
    plan = root['Plan']
    execution_ms = float(root.get('Execution Time', plan.get('Actual Total Time', 0.0)))
    total_cost = float(plan.get('Total Cost', 0.0))
    seq: list[tuple[str, int]] = []
    for node in _walk(plan):
        if node.get('Node Type') == 'Seq Scan':
            rows = int(node.get('Plan Rows', node.get('Actual Rows', 0)) or 0)
            if rows >= policy.forbid_seq_scan_above_rows:
                seq.append((str(node.get('Relation Name', 'unknown')), rows))
    reasons: list[str] = []
    if execution_ms > policy.max_execution_ms:
        reasons.append('execution_time_exceeded')
    if total_cost > policy.max_total_cost:
        reasons.append('plan_cost_exceeded')
    if seq:
        reasons.append('large_sequential_scan')
    return ExplainPlanResult(not reasons, execution_ms, total_cost, tuple(seq), tuple(reasons))
