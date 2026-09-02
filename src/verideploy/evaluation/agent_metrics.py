from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class AgentToolEvent:
    tool_name: str
    success: bool
    trace_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class AgentFailureEvent:
    failure_id: str
    component: str
    trace_id: str | None = None
    span_id: str | None = None


@dataclass(frozen=True)
class AgentObservation:
    case_id: str
    category: str
    expected_route: str
    actual_route: str
    expected_plan: tuple[str, ...]
    actual_plan: tuple[str, ...]
    expected_tools: frozenset[str]
    tool_events: tuple[AgentToolEvent, ...]
    task_completed: bool
    retry_count: int
    retry_budget: int
    expected_escalation: bool
    actual_escalation: bool
    expected_path: tuple[str, ...]
    actual_path: tuple[str, ...]
    failures: tuple[AgentFailureEvent, ...] = ()
    correlation_id: str | None = None
    repeat: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentCaseMetrics:
    case_id: str
    category: str
    repeat: int
    routing_accuracy: float
    planning_quality: float
    tool_selection_correctness: float
    task_completion: float
    tool_success: float
    retry_efficiency: float
    retry_count: int
    escalation_accuracy: float
    path_correctness: float
    failure_trace_linkage: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "repeat": self.repeat,
            "routing_accuracy": self.routing_accuracy,
            "planning_quality": self.planning_quality,
            "tool_selection_correctness": self.tool_selection_correctness,
            "task_completion": self.task_completion,
            "tool_success": self.tool_success,
            "retry_efficiency": self.retry_efficiency,
            "retry_count": self.retry_count,
            "escalation_accuracy": self.escalation_accuracy,
            "path_correctness": self.path_correctness,
            "failure_trace_linkage": self.failure_trace_linkage,
        }


def _lcs_length(expected: Sequence[str], actual: Sequence[str]) -> int:
    if not expected or not actual:
        return 0
    previous = [0] * (len(actual) + 1)
    for expected_item in expected:
        current = [0]
        for index, actual_item in enumerate(actual, start=1):
            if expected_item == actual_item:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(current[-1], previous[index]))
        previous = current
    return previous[-1]


def sequence_f1(expected: Sequence[str], actual: Sequence[str]) -> float:
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    overlap = _lcs_length(expected, actual)
    precision = overlap / len(actual)
    recall = overlap / len(expected)
    if precision + recall == 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def set_f1(expected: set[str] | frozenset[str], actual: set[str] | frozenset[str]) -> float:
    expected_set = set(expected)
    actual_set = set(actual)
    if not expected_set and not actual_set:
        return 1.0
    if not expected_set or not actual_set:
        return 0.0
    overlap = len(expected_set & actual_set)
    precision = overlap / len(actual_set)
    recall = overlap / len(expected_set)
    if precision + recall == 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def retry_efficiency(retry_count: int, retry_budget: int) -> float:
    retries = max(0, retry_count)
    budget = max(0, retry_budget)
    if retries <= budget:
        return 1.0
    excess = retries - budget
    return max(0.0, 1.0 - (excess / max(2.0, float(budget + 2))))


def tool_success_rate(events: Sequence[AgentToolEvent], expected_tools: set[str] | frozenset[str]) -> float:
    if not events:
        return 1.0 if not expected_tools else 0.0
    return sum(1 for event in events if event.success) / len(events)


def failure_trace_linkage(failures: Sequence[AgentFailureEvent]) -> float:
    if not failures:
        return 1.0
    linked = sum(1 for failure in failures if failure.trace_id and failure.span_id)
    return linked / len(failures)


def score_observation(observation: AgentObservation) -> AgentCaseMetrics:
    actual_tools = frozenset(event.tool_name for event in observation.tool_events)
    return AgentCaseMetrics(
        case_id=observation.case_id,
        category=observation.category,
        repeat=observation.repeat,
        routing_accuracy=1.0 if observation.actual_route == observation.expected_route else 0.0,
        planning_quality=sequence_f1(observation.expected_plan, observation.actual_plan),
        tool_selection_correctness=set_f1(observation.expected_tools, actual_tools),
        task_completion=1.0 if observation.task_completed else 0.0,
        tool_success=tool_success_rate(observation.tool_events, observation.expected_tools),
        retry_efficiency=retry_efficiency(observation.retry_count, observation.retry_budget),
        retry_count=max(0, observation.retry_count),
        escalation_accuracy=1.0 if observation.actual_escalation == observation.expected_escalation else 0.0,
        path_correctness=sequence_f1(observation.expected_path, observation.actual_path),
        failure_trace_linkage=failure_trace_linkage(observation.failures),
    )


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def summarize_metrics(metrics: Iterable[AgentCaseMetrics]) -> dict[str, float | int]:
    rows = list(metrics)
    score_fields = (
        "routing_accuracy",
        "planning_quality",
        "tool_selection_correctness",
        "task_completion",
        "tool_success",
        "retry_efficiency",
        "escalation_accuracy",
        "path_correctness",
        "failure_trace_linkage",
    )
    result: dict[str, float | int] = {"case_observations": len(rows)}
    for field_name in score_fields:
        result[field_name] = _mean([float(getattr(row, field_name)) for row in rows])
    result["mean_retry_count"] = _mean([float(row.retry_count) for row in rows])
    result["aggregate_score"] = _mean([float(result[name]) for name in score_fields]) if rows else 0.0
    return result


def summarize_by_category(metrics: Iterable[AgentCaseMetrics]) -> dict[str, dict[str, float | int]]:
    rows = list(metrics)
    categories = sorted({row.category for row in rows})
    return {category: summarize_metrics(row for row in rows if row.category == category) for category in categories}


def failure_trace_records(observations: Iterable[AgentObservation]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for observation in observations:
        for failure in observation.failures:
            records.append(
                {
                    "case_id": observation.case_id,
                    "category": observation.category,
                    "correlation_id": observation.correlation_id,
                    "failure_id": failure.failure_id,
                    "component": failure.component,
                    "trace_id": failure.trace_id,
                    "span_id": failure.span_id,
                    "linked": bool(failure.trace_id and failure.span_id),
                }
            )
    return records


def evaluate_agent_observations(observations: Iterable[AgentObservation]) -> dict[str, Any]:
    rows = list(observations)
    metrics = [score_observation(row) for row in rows]
    failures = failure_trace_records(rows)
    return {
        "summary": summarize_metrics(metrics),
        "by_category": summarize_by_category(metrics),
        "cases": [metric.as_dict() for metric in metrics],
        "failure_trace_records": failures,
        "unlinked_failure_count": sum(1 for failure in failures if not failure["linked"]),
    }
