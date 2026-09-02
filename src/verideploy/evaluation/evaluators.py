from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from verideploy.evaluation.models import EvalCase, EvaluationScore


class Evaluator(Protocol):
    name: str

    def evaluate(self, case: EvalCase, output: dict[str, Any]) -> EvaluationScore: ...


class ExactFieldsEvaluator:
    name = "exact_fields"

    def evaluate(self, case: EvalCase, output: dict[str, Any]) -> EvaluationScore:
        expected = case.expected
        if not expected:
            return EvaluationScore(evaluator=self.name, score=1.0, passed=True)
        matches = {key: output.get(key) == value for key, value in expected.items()}
        score = sum(matches.values()) / len(matches)
        return EvaluationScore(
            evaluator=self.name,
            score=score,
            passed=score == 1.0,
            details={"field_matches": matches},
        )


class RequiredFieldsEvaluator:
    name = "required_fields"

    def evaluate(self, case: EvalCase, output: dict[str, Any]) -> EvaluationScore:
        required = list(case.metadata.get("required_output_fields", []))
        if not required:
            return EvaluationScore(evaluator=self.name, score=1.0, passed=True)
        present = {field: field in output and output[field] is not None for field in required}
        score = sum(present.values()) / len(present)
        return EvaluationScore(
            evaluator=self.name,
            score=score,
            passed=score == 1.0,
            details={"present": present},
        )


EvaluatorFactory = Callable[[], Evaluator]


REGISTRY: dict[str, EvaluatorFactory] = {
    ExactFieldsEvaluator.name: ExactFieldsEvaluator,
    RequiredFieldsEvaluator.name: RequiredFieldsEvaluator,
}


def load_evaluators(names: list[str]) -> list[Evaluator]:
    missing = sorted(set(names) - REGISTRY.keys())
    if missing:
        raise ValueError(f"unknown evaluators: {', '.join(missing)}")
    return [REGISTRY[name]() for name in names]
