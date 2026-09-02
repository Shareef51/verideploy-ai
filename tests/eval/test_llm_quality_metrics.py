from __future__ import annotations

from verideploy.evaluation.llm_quality_metrics import (
    InstructionContract,
    LLMQualityObservation,
    QualityJudgeCalibrationExample,
    QualityJudgeSpec,
    StructuredOutputContract,
    calibrate_quality_judge,
    compare_variants,
    instruction_adherence,
    reasoning_result_consistency,
    refusal_abstention_correctness,
    score_observation,
    structured_output_validity,
)


def _observation(**overrides):
    values = dict(
        case_id="release-risk-001",
        category="release_risk",
        answer='{"decision":"review","risk":"high"}',
        reference_answer='{"decision":"review","risk":"high"}',
        instruction_contract=InstructionContract(required_terms=frozenset({"decision", "risk"}), required_format="json"),
        structured_contract=StructuredOutputContract(
            required_keys=frozenset({"decision", "risk"}),
            expected_types={"decision": "string", "risk": "string"},
            allowed_values={"decision": frozenset({"deploy", "review", "rollback"})},
        ),
        expected_abstention=False,
        actual_abstention=False,
        reasoning_result="review high risk",
        final_result="review high risk",
        model_id="model-a",
        prompt_id="quality",
        prompt_version="1.0.0",
    )
    values.update(overrides)
    return LLMQualityObservation(**values)


def test_quality_dimensions_are_scored_independently() -> None:
    result = score_observation(
        _observation(
            answer='{"decision":"deploy","risk":"low"}',
            actual_abstention=True,
            abstention_reason="insufficient evidence",
            final_result="deploy low risk",
        )
    )
    assert 0.0 < result.answer_quality < 1.0
    assert result.instruction_adherence == 1.0
    assert result.structured_output_validity == 1.0
    assert result.refusal_abstention_correctness == 0.0
    assert result.reasoning_result_consistency < 1.0


def test_instruction_and_structured_output_contracts_fail_closed() -> None:
    contract = InstructionContract(required_terms=frozenset({"risk"}), forbidden_terms=frozenset({"guess"}), required_format="json")
    assert instruction_adherence("not json and a guess", contract) < 0.5
    structured = StructuredOutputContract(required_keys=frozenset({"decision"}), expected_types={"decision": "string"})
    assert structured_output_validity("not json", structured) == 0.0
    assert structured_output_validity('{"decision":42}', structured) < 1.0


def test_abstention_and_reasoning_result_consistency() -> None:
    assert refusal_abstention_correctness(expected_abstention=True, actual_abstention=True, abstention_reason="no grounded evidence") == 1.0
    assert refusal_abstention_correctness(expected_abstention=True, actual_abstention=False) == 0.0
    assert reasoning_result_consistency("rollback high risk", "rollback high risk") == 1.0
    assert reasoning_result_consistency("rollback high risk", "deploy low risk") < 0.25


def test_judge_calibration_records_prompt_hash_and_passes_good_alignment() -> None:
    spec = QualityJudgeSpec("quality-judge", "evaluation-model", "llm-quality", "1.0.0", "score {{answer}}")
    calibration = calibrate_quality_judge(
        [
            QualityJudgeCalibrationExample("a", 0.2, 0.21),
            QualityJudgeCalibrationExample("b", 0.5, 0.49),
            QualityJudgeCalibrationExample("c", 0.8, 0.79),
            QualityJudgeCalibrationExample("d", 1.0, 0.98),
        ],
        spec=spec,
    )
    assert calibration["passed"] is True
    assert calibration["judge"]["prompt_sha256"] == spec.prompt_sha256


def test_model_prompt_version_comparison_ranks_variants() -> None:
    baseline = score_observation(_observation(model_id="model-a", prompt_version="1.0.0"))
    candidate = score_observation(
        _observation(
            model_id="model-b",
            prompt_version="2.0.0",
            answer='{"decision":"review","risk":"high"}',
            reference_answer='{"decision":"review","risk":"high"}',
        )
    )
    comparison = compare_variants([baseline, candidate], baseline_variant="model-a|quality|1.0.0")
    assert comparison["baseline_variant"] == "model-a|quality|1.0.0"
    assert len(comparison["ranking"]) == 2
    assert comparison["ranking"][0]["aggregate_score"] >= comparison["ranking"][1]["aggregate_score"]
