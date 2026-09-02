from __future__ import annotations

from verideploy.evaluation.agent_metrics import (
    AgentFailureEvent,
    AgentObservation,
    AgentToolEvent,
    evaluate_agent_observations,
    failure_trace_linkage,
    score_observation,
    sequence_f1,
    set_f1,
)


def _observation(**overrides):
    values = dict(
        case_id="rca-001",
        category="rca",
        expected_route="rca",
        actual_route="rca",
        expected_plan=("retrieve", "runtime", "rca", "critic"),
        actual_plan=("retrieve", "runtime", "rca", "critic"),
        expected_tools=frozenset({"retrieval.search", "runtime.metrics"}),
        tool_events=(
            AgentToolEvent("retrieval.search", True),
            AgentToolEvent("runtime.metrics", True),
        ),
        task_completed=True,
        retry_count=1,
        retry_budget=1,
        expected_escalation=False,
        actual_escalation=False,
        expected_path=("supervisor", "rag", "runtime", "rca", "critic", "complete"),
        actual_path=("supervisor", "rag", "runtime", "rca", "critic", "complete"),
        failures=(),
        correlation_id="corr-001",
    )
    values.update(overrides)
    return AgentObservation(**values)


def test_route_plan_tool_and_path_scores_are_independent() -> None:
    result = score_observation(
        _observation(
            actual_route="rag",
            actual_plan=("retrieve", "rca", "critic"),
            tool_events=(AgentToolEvent("retrieval.search", True),),
            actual_path=("supervisor", "rag", "rca", "critic", "complete"),
        )
    )
    assert result.routing_accuracy == 0.0
    assert 0.0 < result.planning_quality < 1.0
    assert 0.0 < result.tool_selection_correctness < 1.0
    assert 0.0 < result.path_correctness < 1.0


def test_sequence_and_tool_set_metrics_reward_exact_behavior() -> None:
    assert sequence_f1(("a", "b", "c"), ("a", "b", "c")) == 1.0
    assert sequence_f1(("a", "b", "c"), ("a", "c")) < 1.0
    assert set_f1(frozenset({"x", "y"}), frozenset({"x", "y"})) == 1.0
    assert set_f1(frozenset({"x", "y"}), frozenset({"x"})) < 1.0


def test_retry_escalation_completion_and_tool_success_are_scored() -> None:
    result = score_observation(
        _observation(
            task_completed=False,
            retry_count=4,
            retry_budget=1,
            expected_escalation=True,
            actual_escalation=False,
            tool_events=(AgentToolEvent("retrieval.search", False), AgentToolEvent("runtime.metrics", True)),
        )
    )
    assert result.task_completion == 0.0
    assert result.retry_efficiency < 1.0
    assert result.escalation_accuracy == 0.0
    assert result.tool_success == 0.5


def test_failure_to_trace_linkage_requires_trace_and_span() -> None:
    failures = (
        AgentFailureEvent("f1", "runtime", "a" * 32, "b" * 16),
        AgentFailureEvent("f2", "tool", "c" * 32, None),
    )
    assert failure_trace_linkage(failures) == 0.5


def test_evaluation_report_links_failures_back_to_case_and_correlation() -> None:
    observation = _observation(
        failures=(AgentFailureEvent("f1", "critic", "a" * 32, "b" * 16),)
    )
    report = evaluate_agent_observations([observation])
    assert report["summary"]["aggregate_score"] == 1.0
    assert report["unlinked_failure_count"] == 0
    link = report["failure_trace_records"][0]
    assert link["case_id"] == "rca-001"
    assert link["correlation_id"] == "corr-001"
    assert link["trace_id"] == "a" * 32
