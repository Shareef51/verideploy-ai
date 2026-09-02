from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from verideploy.evaluation.llm_quality_metrics import (
    InstructionContract,
    LLMQualityObservation,
    QualityJudgeCalibrationExample,
    QualityJudgeSpec,
    StructuredOutputContract,
    calibrate_quality_judge,
    compare_variants,
    score_observation,
    summarize_metrics,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/verideploy-500/v1.jsonl"
DEFAULT_REPORT = ROOT / "evals/reports/llm-quality-metrics.json"
PROMPT = ROOT / "prompts/evaluation/llm_quality_judge_v1.md"

VARIANTS = (
    ("synthetic-quality-baseline", "verideploy-quality", "1.0.0", 32),
    ("synthetic-quality-candidate", "verideploy-quality", "2.0.0", 12),
)

THRESHOLDS = {
    "answer_quality": 0.95,
    "instruction_adherence": 0.98,
    "structured_output_validity": 0.98,
    "refusal_abstention_correctness": 0.98,
    "reasoning_result_consistency": 0.98,
    "aggregate_score": 0.97,
}


def _bucket(case_id: str, salt: str, modulo: int = 1000) -> int:
    digest = hashlib.sha256(f"{case_id}:{salt}".encode()).hexdigest()
    return int(digest[:8], 16) % modulo


def _load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]


def _reference_payload(case: dict[str, Any]) -> dict[str, Any]:
    category = str(case["category"])
    ground_truth = case.get("ground_truth", {})
    expected_abstention = category == "hallucination"
    if expected_abstention:
        result = "abstain"
    elif ground_truth.get("decision"):
        result = str(ground_truth["decision"])
    elif ground_truth.get("root_cause_code"):
        result = str(ground_truth["root_cause_code"])
    elif ground_truth.get("answer"):
        result = str(ground_truth["answer"])
    elif ground_truth.get("relevant_source_ids"):
        result = ",".join(str(item) for item in ground_truth["relevant_source_ids"])
    elif ground_truth.get("allowed_claims"):
        result = " | ".join(str(item) for item in ground_truth["allowed_claims"])
    elif ground_truth.get("claims"):
        result = " | ".join(str(item.get("text", "")) for item in ground_truth["claims"])
    else:
        result = "grounded"
    return {
        "case_id": str(case["case_id"]),
        "category": category,
        "result": result,
        "abstain": expected_abstention,
    }


def _observation(case: dict[str, Any], variant: tuple[str, str, str, int]) -> LLMQualityObservation:
    model_id, prompt_id, prompt_version, error_rate = variant
    case_id = str(case["case_id"])
    category = str(case["category"])
    reference_payload = _reference_payload(case)
    reference_answer = json.dumps(reference_payload, separators=(",", ":"), sort_keys=True)
    answer_payload = dict(reference_payload)
    salt = f"{model_id}:{prompt_version}"

    if _bucket(case_id, salt + ":answer") < error_rate:
        answer_payload["result"] = "unsupported-alternative"
    answer = json.dumps(answer_payload, separators=(",", ":"), sort_keys=True)
    if _bucket(case_id, salt + ":malformed") < max(2, error_rate // 4):
        answer = answer[:-1]

    actual_abstention = bool(reference_payload["abstain"])
    if _bucket(case_id, salt + ":abstention") < max(4, error_rate // 2):
        actual_abstention = not actual_abstention
    abstention_reason = "insufficient grounded evidence" if actual_abstention else None

    reasoning_result = str(reference_payload["result"])
    final_result = str(answer_payload["result"])
    if _bucket(case_id, salt + ":consistency") < max(3, error_rate // 3):
        reasoning_result = "contradictory-intermediate-result"

    instruction_contract = InstructionContract(
        required_terms=frozenset({"case_id", "category", "result", "abstain"}),
        forbidden_terms=frozenset({"fabricated_source", "ignore_policy"}),
        required_format="json",
        max_words=80,
    )
    structured_contract = StructuredOutputContract(
        required_keys=frozenset({"case_id", "category", "result", "abstain"}),
        expected_types={"case_id": "string", "category": "string", "result": "string", "abstain": "boolean"},
        allowed_values={"category": frozenset({"retrieval", "rca", "release_risk", "visual", "document_qa", "hallucination", "citation"})},
    )
    return LLMQualityObservation(
        case_id=case_id,
        category=category,
        answer=answer,
        reference_answer=reference_answer,
        instruction_contract=instruction_contract,
        structured_contract=structured_contract,
        expected_abstention=bool(reference_payload["abstain"]),
        actual_abstention=actual_abstention,
        abstention_reason=abstention_reason,
        reasoning_result=reasoning_result,
        final_result=final_result,
        model_id=model_id,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        metadata={"dataset": "verideploy-500", "dataset_version": "1", "offline_profile": True},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic LLM quality benchmark")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    cases = _load_cases()
    observations = [_observation(case, variant) for variant in VARIANTS for case in cases]
    metrics = [score_observation(item) for item in observations]
    comparison = compare_variants(metrics, baseline_variant="synthetic-quality-baseline|verideploy-quality|1.0.0")
    candidate_key = "synthetic-quality-candidate|verideploy-quality|2.0.0"
    candidate_summary = comparison["variants"][candidate_key]

    prompt = PROMPT.read_text(encoding="utf-8")
    judge_spec = QualityJudgeSpec(
        judge_name="verideploy-llm-quality",
        model_id="evaluation-model-role",
        prompt_id="llm-quality-judge",
        prompt_version="1.0.0",
        prompt_template=prompt,
    )
    calibration = calibrate_quality_judge(
        [
            QualityJudgeCalibrationExample("cal-1", 0.15, 0.16),
            QualityJudgeCalibrationExample("cal-2", 0.35, 0.34),
            QualityJudgeCalibrationExample("cal-3", 0.55, 0.57),
            QualityJudgeCalibrationExample("cal-4", 0.75, 0.74),
            QualityJudgeCalibrationExample("cal-5", 0.95, 0.93),
        ],
        spec=judge_spec,
    )

    checks = {name: float(candidate_summary[name]) >= threshold for name, threshold in THRESHOLDS.items()}
    checks["judge_calibration"] = bool(calibration["passed"])
    checks["candidate_not_worse_than_baseline"] = float(candidate_summary["aggregate_score"]) >= float(
        comparison["variants"][comparison["baseline_variant"]]["aggregate_score"]
    )
    passed = all(checks.values())

    report = {
        "dataset": "evals/datasets/verideploy-500/v1.jsonl",
        "dataset_case_count": len(cases),
        "case_observations": len(observations),
        "deterministic_rule_based": True,
        "model_judge_default_enabled": False,
        "benchmark_profiles_are_synthetic": True,
        "candidate_summary": candidate_summary,
        "all_observations_summary": summarize_metrics(metrics),
        "comparison": comparison,
        "judge_calibration": calibration,
        "thresholds": THRESHOLDS,
        "checks": checks,
        "passed": passed,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_summary": candidate_summary, "ranking": comparison["ranking"], "judge_calibration": calibration, "passed": passed}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
