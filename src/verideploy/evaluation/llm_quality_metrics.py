from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class InstructionContract:
    required_terms: frozenset[str] = frozenset()
    forbidden_terms: frozenset[str] = frozenset()
    required_format: str | None = None
    max_words: int | None = None


@dataclass(frozen=True)
class StructuredOutputContract:
    required_keys: frozenset[str] = frozenset()
    expected_types: Mapping[str, str] = field(default_factory=dict)
    allowed_values: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMQualityObservation:
    case_id: str
    category: str
    answer: str
    reference_answer: str
    instruction_contract: InstructionContract = InstructionContract()
    structured_contract: StructuredOutputContract | None = None
    expected_abstention: bool = False
    actual_abstention: bool = False
    abstention_reason: str | None = None
    reasoning_result: str | None = None
    final_result: str | None = None
    model_id: str = "deterministic-baseline"
    prompt_id: str = "default"
    prompt_version: str = "1.0.0"
    repeat: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMQualityCaseMetrics:
    case_id: str
    category: str
    model_id: str
    prompt_id: str
    prompt_version: str
    repeat: int
    answer_quality: float
    instruction_adherence: float
    structured_output_validity: float
    refusal_abstention_correctness: float
    reasoning_result_consistency: float

    @property
    def aggregate_score(self) -> float:
        return statistics.fmean(
            (
                self.answer_quality,
                self.instruction_adherence,
                self.structured_output_validity,
                self.refusal_abstention_correctness,
                self.reasoning_result_consistency,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "model_id": self.model_id,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "repeat": self.repeat,
            "answer_quality": self.answer_quality,
            "instruction_adherence": self.instruction_adherence,
            "structured_output_validity": self.structured_output_validity,
            "refusal_abstention_correctness": self.refusal_abstention_correctness,
            "reasoning_result_consistency": self.reasoning_result_consistency,
            "aggregate_score": self.aggregate_score,
        }


@dataclass(frozen=True)
class QualityJudgeSpec:
    judge_name: str
    model_id: str
    prompt_id: str
    prompt_version: str
    prompt_template: str

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt_template.encode("utf-8")).hexdigest()

    def manifest(self) -> dict[str, str]:
        return {
            "judge_name": self.judge_name,
            "model_id": self.model_id,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
        }


@dataclass(frozen=True)
class QualityJudgeRequest:
    observation: LLMQualityObservation
    deterministic_metrics: LLMQualityCaseMetrics
    spec: QualityJudgeSpec


@dataclass(frozen=True)
class QualityJudgeResult:
    score: float
    rationale: str
    raw: Mapping[str, Any] = field(default_factory=dict)


QualityJudgeCallable = Callable[[QualityJudgeRequest], QualityJudgeResult]


@dataclass(frozen=True)
class QualityJudgeCalibrationExample:
    example_id: str
    gold_score: float
    judge_score: float


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _token_f1(expected: str, actual: str) -> float:
    expected_tokens = _tokens(expected)
    actual_tokens = _tokens(actual)
    if not expected_tokens and not actual_tokens:
        return 1.0
    if not expected_tokens or not actual_tokens:
        return 0.0
    expected_counts: dict[str, int] = {}
    actual_counts: dict[str, int] = {}
    for token in expected_tokens:
        expected_counts[token] = expected_counts.get(token, 0) + 1
    for token in actual_tokens:
        actual_counts[token] = actual_counts.get(token, 0) + 1
    overlap = sum(min(count, actual_counts.get(token, 0)) for token, count in expected_counts.items())
    precision = overlap / len(actual_tokens)
    recall = overlap / len(expected_tokens)
    return 0.0 if precision + recall == 0 else 2.0 * precision * recall / (precision + recall)


def answer_quality(reference_answer: str, answer: str) -> float:
    return _token_f1(reference_answer, answer)


def instruction_adherence(answer: str, contract: InstructionContract) -> float:
    checks: list[bool] = []
    lowered = answer.lower()
    checks.extend(term.lower() in lowered for term in sorted(contract.required_terms))
    checks.extend(term.lower() not in lowered for term in sorted(contract.forbidden_terms))
    if contract.max_words is not None:
        checks.append(len(answer.split()) <= contract.max_words)
    if contract.required_format:
        required_format = contract.required_format.lower()
        if required_format == "json":
            try:
                json.loads(answer)
                checks.append(True)
            except (TypeError, ValueError, json.JSONDecodeError):
                checks.append(False)
        elif required_format == "bullet_list":
            nonempty = [line.strip() for line in answer.splitlines() if line.strip()]
            checks.append(bool(nonempty) and all(line.startswith(("- ", "* ")) for line in nonempty))
        else:
            checks.append(required_format in lowered)
    return 1.0 if not checks else sum(checks) / len(checks)


def _type_matches(value: Any, expected_type: str) -> bool:
    mapping: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "number": (int, float),
        "integer": (int,),
        "boolean": (bool,),
        "object": (dict,),
        "array": (list,),
        "null": (type(None),),
    }
    expected = mapping.get(expected_type.lower())
    if expected is None:
        raise ValueError(f"unsupported expected type: {expected_type}")
    if expected_type.lower() in {"number", "integer"} and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def structured_output_validity(answer: str, contract: StructuredOutputContract | None) -> float:
    if contract is None:
        return 1.0
    try:
        payload = json.loads(answer)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0.0
    if not isinstance(payload, dict):
        return 0.0
    checks: list[bool] = []
    checks.extend(key in payload for key in sorted(contract.required_keys))
    for key, expected_type in sorted(contract.expected_types.items()):
        checks.append(key in payload and _type_matches(payload.get(key), expected_type))
    for key, allowed in sorted(contract.allowed_values.items()):
        checks.append(key in payload and str(payload.get(key)) in allowed)
    return 1.0 if not checks else sum(checks) / len(checks)


def refusal_abstention_correctness(
    *, expected_abstention: bool, actual_abstention: bool, abstention_reason: str | None = None
) -> float:
    if expected_abstention != actual_abstention:
        return 0.0
    if expected_abstention:
        return 1.0 if abstention_reason and abstention_reason.strip() else 0.5
    return 1.0


def reasoning_result_consistency(reasoning_result: str | None, final_result: str | None) -> float:
    if reasoning_result is None and final_result is None:
        return 1.0
    if reasoning_result is None or final_result is None:
        return 0.0
    left = " ".join(_tokens(reasoning_result))
    right = " ".join(_tokens(final_result))
    if not left and not right:
        return 1.0
    if left == right:
        return 1.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def score_observation(observation: LLMQualityObservation) -> LLMQualityCaseMetrics:
    return LLMQualityCaseMetrics(
        case_id=observation.case_id,
        category=observation.category,
        model_id=observation.model_id,
        prompt_id=observation.prompt_id,
        prompt_version=observation.prompt_version,
        repeat=observation.repeat,
        answer_quality=answer_quality(observation.reference_answer, observation.answer),
        instruction_adherence=instruction_adherence(observation.answer, observation.instruction_contract),
        structured_output_validity=structured_output_validity(observation.answer, observation.structured_contract),
        refusal_abstention_correctness=refusal_abstention_correctness(
            expected_abstention=observation.expected_abstention,
            actual_abstention=observation.actual_abstention,
            abstention_reason=observation.abstention_reason,
        ),
        reasoning_result_consistency=reasoning_result_consistency(
            observation.reasoning_result, observation.final_result
        ),
    )


def summarize_metrics(metrics: Iterable[LLMQualityCaseMetrics]) -> dict[str, float | int]:
    rows = list(metrics)
    fields = (
        "answer_quality",
        "instruction_adherence",
        "structured_output_validity",
        "refusal_abstention_correctness",
        "reasoning_result_consistency",
    )
    result: dict[str, float | int] = {"case_observations": len(rows)}
    for name in fields:
        values = [float(getattr(row, name)) for row in rows]
        result[name] = statistics.fmean(values) if values else 0.0
    result["aggregate_score"] = statistics.fmean(float(result[name]) for name in fields) if rows else 0.0
    return result


def summarize_by_variant(metrics: Iterable[LLMQualityCaseMetrics]) -> dict[str, dict[str, float | int]]:
    rows = list(metrics)
    keys = sorted({(row.model_id, row.prompt_id, row.prompt_version) for row in rows})
    return {
        f"{model_id}|{prompt_id}|{prompt_version}": summarize_metrics(
            row
            for row in rows
            if (row.model_id, row.prompt_id, row.prompt_version) == (model_id, prompt_id, prompt_version)
        )
        for model_id, prompt_id, prompt_version in keys
    }


def compare_variants(
    metrics: Iterable[LLMQualityCaseMetrics], *, baseline_variant: str | None = None
) -> dict[str, Any]:
    variants = summarize_by_variant(metrics)
    if not variants:
        return {"baseline_variant": None, "variants": {}, "ranking": []}
    baseline = baseline_variant or sorted(variants)[0]
    if baseline not in variants:
        raise ValueError(f"unknown baseline variant: {baseline}")
    baseline_score = float(variants[baseline]["aggregate_score"])
    ranking = sorted(
        (
            {
                "variant": name,
                "aggregate_score": float(summary["aggregate_score"]),
                "delta_vs_baseline": float(summary["aggregate_score"]) - baseline_score,
            }
            for name, summary in variants.items()
        ),
        key=lambda item: (-item["aggregate_score"], item["variant"]),
    )
    return {"baseline_variant": baseline, "variants": variants, "ranking": ranking}


def run_optional_quality_judge(
    observation: LLMQualityObservation,
    *,
    enabled: bool,
    spec: QualityJudgeSpec,
    judge: QualityJudgeCallable | None = None,
) -> dict[str, Any]:
    manifest = spec.manifest()
    if not enabled:
        return {"enabled": False, "executed": False, "judge": manifest}
    if judge is None:
        raise ValueError("judge callable is required when model judging is enabled")
    deterministic = score_observation(observation)
    result = judge(QualityJudgeRequest(observation=observation, deterministic_metrics=deterministic, spec=spec))
    return {
        "enabled": True,
        "executed": True,
        "judge": manifest,
        "score": min(1.0, max(0.0, float(result.score))),
        "rationale": result.rationale,
        "raw": dict(result.raw),
    }


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


def calibrate_quality_judge(
    examples: Sequence[QualityJudgeCalibrationExample],
    *,
    spec: QualityJudgeSpec,
    max_mae: float = 0.08,
    min_correlation: float = 0.92,
) -> dict[str, Any]:
    if not examples:
        raise ValueError("at least one calibration example is required")
    gold = [min(1.0, max(0.0, item.gold_score)) for item in examples]
    judged = [min(1.0, max(0.0, item.judge_score)) for item in examples]
    errors = [predicted - expected for expected, predicted in zip(gold, judged)]
    mae = statistics.fmean(abs(error) for error in errors)
    bias = statistics.fmean(errors)
    correlation = _pearson(gold, judged)
    passed = mae <= max_mae and (len(examples) < 2 or correlation >= min_correlation)
    return {
        "judge": spec.manifest(),
        "examples": len(examples),
        "mae": mae,
        "bias": bias,
        "pearson_correlation": correlation,
        "thresholds": {"max_mae": max_mae, "min_correlation": min_correlation},
        "passed": passed,
    }
