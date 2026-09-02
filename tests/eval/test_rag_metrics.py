from __future__ import annotations

from verideploy.evaluation.rag_metrics import (
    JudgeCalibrationExample,
    JudgeResult,
    JudgeSpec,
    RAGClaim,
    RAGContext,
    RAGObservation,
    answer_relevance,
    calibrate_model_judge,
    citation_completeness,
    citation_correctness,
    context_precision,
    context_recall,
    faithfulness,
    run_optional_model_judge,
    score_observation,
)


def _observation() -> RAGObservation:
    contexts = (
        RAGContext("source-a", "policy says rollback after two failed gates", True),
        RAGContext("source-b", "unrelated context", False),
    )
    claim = RAGClaim("c1", "Rollback follows two failed gates.", ("source-a",), frozenset({"source-a"}), True)
    return RAGObservation(
        "document-qa-001",
        "When is rollback authorized?",
        "Rollback follows two failed gates.",
        contexts,
        frozenset({"source-a"}),
        (claim,),
        reference_answer="Rollback follows two failed gates.",
    )


def test_context_precision_and_recall_are_distinct() -> None:
    observation = _observation()
    assert context_precision(observation.contexts) == 0.5
    assert context_recall(observation.contexts, observation.required_source_ids) == 1.0


def test_relevance_and_faithfulness_are_deterministic() -> None:
    observation = _observation()
    assert answer_relevance(observation.question, observation.answer, observation.reference_answer) == 1.0
    assert faithfulness(observation.claims, observation.contexts) == 1.0


def test_citation_correctness_and_completeness_detect_different_failures() -> None:
    contexts = (RAGContext("a", relevant=True), RAGContext("b", relevant=True))
    claims = (
        RAGClaim("c1", "one", ("a",), frozenset({"a"}), True),
        RAGClaim("c2", "two", (), frozenset({"b"}), True),
    )
    assert citation_correctness(claims, contexts) == 1.0
    assert citation_completeness(claims, contexts) == 0.5
    wrong = (RAGClaim("c1", "one", ("b",), frozenset({"a"}), True),)
    assert citation_correctness(wrong, contexts) == 0.0


def test_score_observation_emits_all_metrics() -> None:
    result = score_observation(_observation())
    assert result.context_precision == 0.5
    assert result.context_recall == 1.0
    assert result.relevance == 1.0
    assert result.faithfulness == 1.0
    assert result.citation_correctness == 1.0
    assert result.citation_completeness == 1.0


def test_optional_judge_is_disabled_by_default_and_calibration_is_versioned() -> None:
    observation = _observation()
    spec = JudgeSpec("judge", "evaluation", "rag-quality", "1.0.0", "score only supplied evidence")
    disabled = run_optional_model_judge(observation, enabled=False, spec=spec)
    assert disabled["executed"] is False
    assert disabled["judge"]["prompt_sha256"] == spec.prompt_sha256

    def fake_judge(_request):
        return JudgeResult(0.97, "well grounded")

    enabled = run_optional_model_judge(observation, enabled=True, spec=spec, judge=fake_judge)
    assert enabled["executed"] is True
    assert enabled["score"] == 0.97

    calibration = calibrate_model_judge(
        [
            JudgeCalibrationExample("1", 0.2, 0.21),
            JudgeCalibrationExample("2", 0.5, 0.49),
            JudgeCalibrationExample("3", 0.8, 0.79),
            JudgeCalibrationExample("4", 1.0, 0.98),
        ],
        spec=spec,
    )
    assert calibration["passed"] is True
    assert calibration["judge"]["prompt_version"] == "1.0.0"
