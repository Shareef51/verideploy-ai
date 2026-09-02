from __future__ import annotations

from verideploy.evaluation.safety_metrics import (
    SafetyObservation,
    adversarial_gate,
    authorization_boundary_correctness,
    policy_violation_detection,
    prompt_injection_resistance,
    score_observation,
    summarize_metrics,
    unsupported_claim_rate,
)


def test_unsupported_claim_rate_is_explicit() -> None:
    assert unsupported_claim_rate(("a", "b"), frozenset({"a"})) == 0.5
    assert unsupported_claim_rate((), frozenset()) == 0.0


def test_injection_and_authorization_fail_closed() -> None:
    assert prompt_injection_resistance(injection_present=True, injection_followed=False) == 1.0
    assert prompt_injection_resistance(injection_present=True, injection_followed=True) == 0.0
    assert authorization_boundary_correctness(
        authorization_required=True,
        authorization_granted=True,
        attempted_cross_boundary_access=True,
        cross_boundary_access_succeeded=False,
    ) == 1.0


def test_policy_detection_penalizes_misses_and_false_positives() -> None:
    assert policy_violation_detection(frozenset({"p1"}), frozenset({"p1"})) == 1.0
    assert policy_violation_detection(frozenset({"p1"}), frozenset()) == 0.0
    assert 0.0 < policy_violation_detection(frozenset({"p1"}), frozenset({"p1", "p2"})) < 1.0


def test_failed_case_requires_trace_linkage() -> None:
    metric = score_observation(
        SafetyObservation(
            case_id="x",
            category="hallucination",
            claims=("unsupported",),
            supported_claims=frozenset(),
            correlation_id="corr-x",
            trace_id="trace-x",
            span_id="span-x",
        )
    )
    assert metric.unsupported_claim_rate == 1.0
    assert metric.failure_trace_linkage == 1.0


def test_adversarial_gate_handles_rates_and_positive_scores() -> None:
    good = score_observation(SafetyObservation(case_id="good", category="retrieval"))
    summary = summarize_metrics([good])
    gate = adversarial_gate(summary, {"unsupported_claim_rate": 0.01, "safety_score": 0.95})
    assert gate["passed"] is True
