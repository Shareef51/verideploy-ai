from pathlib import Path

from verideploy.orchestration.checkpoint import OrchestrationPerformanceCheckpoint, run_orchestration_checkpoint

ROOT = Path(__file__).resolve().parents[2]


def test_all_deterministic_scenarios_complete_and_recover():
    report = run_orchestration_checkpoint(ROOT)
    assert report["gate"] == "pass"
    assert report["scenario_count"] == 3
    assert all(row["completed"] for row in report["scenarios"])
    assert all(row["recovered_after_restart"] for row in report["scenarios"])


def test_retry_is_bounded_and_trace_linked():
    report = run_orchestration_checkpoint(ROOT)
    retry = next(row for row in report["scenarios"] if row["case_id"] == "incident-rca-retry-recovery")
    assert retry["retry_count"] == 1
    assert retry["retry_count"] <= report["retry_budget"]
    assert report["metrics"]["summary"]["failure_trace_linkage"] == 1.0
    assert report["metrics"]["unlinked_failure_count"] == 0


def test_fanout_fanin_and_critic_loop_are_complete():
    report = run_orchestration_checkpoint(ROOT)
    release = next(row for row in report["scenarios"] if row["case_id"] == "release-risk-parallel")
    critic = next(row for row in report["scenarios"] if row["case_id"] == "critic-correction")
    assert release["fan_in_complete"] is True
    assert "fan_out" in release["path"] and "fan_in" in release["path"]
    assert critic["critic_corrected"] is True
    assert critic["path"].count("critic") == 2
    assert "rag_followup" in critic["path"]


def test_consequential_path_stops_at_human_approval():
    report = run_orchestration_checkpoint(ROOT)
    approval_rows = [row for row in report["scenarios"] if row["approval_blocked"]]
    assert {row["case_id"] for row in approval_rows} == {"incident-rca-retry-recovery", "critic-correction"}
    assert all(row["path"][-1] == "approval" for row in approval_rows)


def test_path_metrics_are_perfect_for_protected_scenarios():
    report = run_orchestration_checkpoint(ROOT)
    summary = report["metrics"]["summary"]
    for field in (
        "routing_accuracy",
        "planning_quality",
        "tool_selection_correctness",
        "task_completion",
        "retry_efficiency",
        "escalation_accuracy",
        "path_correctness",
        "failure_trace_linkage",
    ):
        assert summary[field] == 1.0
