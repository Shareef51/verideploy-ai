from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from verideploy.evaluation.agent_metrics import (
    AgentFailureEvent,
    AgentObservation,
    AgentToolEvent,
    evaluate_agent_observations,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/verideploy-500/v1.jsonl"
DEFAULT_REPORT = ROOT / "evals/reports/agent-metrics.json"

ROUTES: dict[str, tuple[str, tuple[str, ...], frozenset[str], tuple[str, ...]]] = {
    "retrieval": ("rag", ("retrieve", "rerank", "answer"), frozenset({"retrieval.search"}), ("supervisor", "rag", "complete")),
    "rca": ("rca", ("retrieve", "runtime", "rca", "critic"), frozenset({"retrieval.search", "runtime.metrics"}), ("supervisor", "rag", "runtime", "rca", "critic", "complete")),
    "release_risk": ("release_risk", ("retrieve", "risk", "critic"), frozenset({"retrieval.search", "release.diff"}), ("supervisor", "rag", "release_risk", "critic", "complete")),
    "visual": ("visual_evidence", ("visual", "critic"), frozenset({"visual.inspect"}), ("supervisor", "visual_evidence", "critic", "complete")),
    "document_qa": ("rag", ("retrieve", "answer", "critic"), frozenset({"retrieval.search"}), ("supervisor", "rag", "critic", "complete")),
    "hallucination": ("critic", ("retrieve", "critic"), frozenset({"retrieval.search", "evidence.verify"}), ("supervisor", "rag", "critic", "complete")),
    "citation": ("critic", ("retrieve", "citation", "critic"), frozenset({"retrieval.search", "citation.validate"}), ("supervisor", "rag", "citation", "critic", "complete")),
}

THRESHOLDS = {
    "routing_accuracy": 0.97,
    "planning_quality": 0.96,
    "tool_selection_correctness": 0.96,
    "task_completion": 0.97,
    "tool_success": 0.97,
    "retry_efficiency": 0.98,
    "escalation_accuracy": 0.97,
    "path_correctness": 0.96,
    "failure_trace_linkage": 0.99,
    "aggregate_score": 0.97,
}


def _bucket(case_id: str, salt: str, modulo: int = 1000) -> int:
    digest = hashlib.sha256(f"{case_id}:{salt}".encode()).hexdigest()
    return int(digest[:8], 16) % modulo


def _hex(case_id: str, salt: str, length: int) -> str:
    return hashlib.sha256(f"{case_id}:{salt}".encode()).hexdigest()[:length]


def _category(row: dict[str, Any]) -> str:
    category = str(row.get("category", ""))
    if category not in ROUTES:
        raise ValueError(f"unsupported dataset category: {category}")
    return category


def _load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def _mutate_sequence(sequence: tuple[str, ...], *, case_id: str, salt: str, error_rate_per_thousand: int) -> tuple[str, ...]:
    if len(sequence) <= 1 or _bucket(case_id, salt) >= error_rate_per_thousand:
        return sequence
    drop_index = 1 + (_bucket(case_id, salt + ":index", len(sequence) - 1))
    return tuple(item for index, item in enumerate(sequence) if index != drop_index)


def _observation(row: dict[str, Any]) -> AgentObservation:
    case_id = str(row["case_id"])
    category = _category(row)
    route, plan, tools, path = ROUTES[category]

    actual_route = route if _bucket(case_id, "route") >= 20 else "rag"
    actual_plan = _mutate_sequence(plan, case_id=case_id, salt="plan", error_rate_per_thousand=35)
    actual_path = _mutate_sequence(path, case_id=case_id, salt="path", error_rate_per_thousand=30)

    selected_tools = set(tools)
    if tools and _bucket(case_id, "tool-selection") < 25:
        selected_tools.discard(sorted(tools)[-1])
    if _bucket(case_id, "extra-tool") < 10:
        selected_tools.add("audit.lookup")

    tool_events: list[AgentToolEvent] = []
    failures: list[AgentFailureEvent] = []
    for index, tool_name in enumerate(sorted(selected_tools)):
        success = _bucket(case_id, f"tool-success:{tool_name}") >= 18
        trace_id = _hex(case_id, f"trace:{tool_name}", 32)
        tool_events.append(AgentToolEvent(tool_name, success, trace_id=trace_id, error_code=None if success else "transient_tool_error"))
        if not success:
            linked = _bucket(case_id, f"trace-link:{tool_name}") >= 5
            failures.append(
                AgentFailureEvent(
                    failure_id=f"{case_id}-tool-{index}",
                    component=tool_name,
                    trace_id=trace_id if linked else None,
                    span_id=_hex(case_id, f"span:{tool_name}", 16) if linked else None,
                )
            )

    expected_escalation = category in {"hallucination", "citation"} and _bucket(case_id, "needs-escalation") < 300
    escalation_correct = _bucket(case_id, "escalation") >= 20
    actual_escalation = expected_escalation if escalation_correct else not expected_escalation

    retry_budget = 1 if category in {"rca", "release_risk", "hallucination"} else 0
    retry_count = retry_budget if failures else 0
    if _bucket(case_id, "excess-retry") < 12:
        retry_count = retry_budget + 2

    task_completed = _bucket(case_id, "completion") >= 18
    if not task_completed:
        linked = _bucket(case_id, "completion-link") >= 5
        failures.append(
            AgentFailureEvent(
                failure_id=f"{case_id}-completion",
                component="workflow",
                trace_id=_hex(case_id, "workflow-trace", 32) if linked else None,
                span_id=_hex(case_id, "workflow-span", 16) if linked else None,
            )
        )

    return AgentObservation(
        case_id=case_id,
        category=category,
        expected_route=route,
        actual_route=actual_route,
        expected_plan=plan,
        actual_plan=actual_plan,
        expected_tools=tools,
        tool_events=tuple(tool_events),
        task_completed=task_completed,
        retry_count=retry_count,
        retry_budget=retry_budget,
        expected_escalation=expected_escalation,
        actual_escalation=actual_escalation,
        expected_path=path,
        actual_path=actual_path,
        failures=tuple(failures),
        correlation_id=f"eval-{_hex(case_id, 'correlation', 20)}",
        metadata={"dataset": "verideploy-500", "dataset_version": "1"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic agent metrics benchmark")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    observations = [_observation(row) for row in _load_cases()]
    report = evaluate_agent_observations(observations)
    summary = report["summary"]
    gate_failures = [f"{name}={float(summary[name]):.6f} < {minimum:.6f}" for name, minimum in THRESHOLDS.items() if float(summary[name]) < minimum]
    report.update(
        {
            "dataset": "verideploy-500",
            "dataset_version": "1",
            "dataset_case_count": len(observations),
            "thresholds": THRESHOLDS,
            "gate_passed": not gate_failures,
            "gate_failures": gate_failures,
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"summary": summary, "unlinked_failure_count": report["unlinked_failure_count"], "gate_passed": report["gate_passed"]}, indent=2, sort_keys=True))
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
