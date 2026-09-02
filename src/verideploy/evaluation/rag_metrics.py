from __future__ import annotations

import hashlib
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RAGContext:
    source_id: str
    text: str = ""
    relevant: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RAGClaim:
    claim_id: str
    text: str
    cited_source_ids: tuple[str, ...] = ()
    supported_by_source_ids: frozenset[str] = frozenset()
    requires_citation: bool = True


@dataclass(frozen=True)
class RAGObservation:
    case_id: str
    question: str
    answer: str
    contexts: tuple[RAGContext, ...]
    required_source_ids: frozenset[str]
    claims: tuple[RAGClaim, ...]
    reference_answer: str | None = None
    repeat: int = 0


@dataclass(frozen=True)
class RAGCaseMetrics:
    case_id: str
    repeat: int
    context_precision: float
    context_recall: float
    relevance: float
    faithfulness: float
    citation_correctness: float
    citation_completeness: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "repeat": self.repeat,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
            "relevance": self.relevance,
            "faithfulness": self.faithfulness,
            "citation_correctness": self.citation_correctness,
            "citation_completeness": self.citation_completeness,
        }


@dataclass(frozen=True)
class JudgeSpec:
    judge_name: str
    model_role: str
    prompt_id: str
    prompt_version: str
    prompt_template: str

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt_template.encode("utf-8")).hexdigest()

    def manifest(self) -> dict[str, str]:
        return {
            "judge_name": self.judge_name,
            "model_role": self.model_role,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
        }


@dataclass(frozen=True)
class JudgeRequest:
    case_id: str
    question: str
    answer: str
    contexts: tuple[RAGContext, ...]
    deterministic_scores: dict[str, float]
    spec: JudgeSpec


@dataclass(frozen=True)
class JudgeResult:
    score: float
    rationale: str
    raw: dict[str, Any] = field(default_factory=dict)


JudgeCallable = Callable[[JudgeRequest], JudgeResult]


@dataclass(frozen=True)
class JudgeCalibrationExample:
    case_id: str
    deterministic_score: float
    judge_score: float


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def context_precision(contexts: Sequence[RAGContext]) -> float:
    if not contexts:
        return 1.0
    return sum(1 for context in contexts if context.relevant) / len(contexts)


def context_recall(contexts: Sequence[RAGContext], required_source_ids: set[str] | frozenset[str]) -> float:
    required = set(required_source_ids)
    if not required:
        return 1.0
    retrieved = {context.source_id for context in contexts}
    return len(retrieved & required) / len(required)


def answer_relevance(question: str, answer: str, reference_answer: str | None = None) -> float:
    answer_tokens = _tokens(answer)
    target_tokens = _tokens(reference_answer or question)
    if not target_tokens:
        return 1.0
    if not answer_tokens:
        return 0.0
    overlap = len(answer_tokens & target_tokens)
    precision = overlap / len(answer_tokens)
    recall = overlap / len(target_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def claim_is_supported(claim: RAGClaim, contexts: Sequence[RAGContext]) -> bool:
    available = {context.source_id for context in contexts}
    return bool(claim.supported_by_source_ids) and bool(available & set(claim.supported_by_source_ids))


def faithfulness(claims: Sequence[RAGClaim], contexts: Sequence[RAGContext]) -> float:
    if not claims:
        return 1.0
    return sum(1 for claim in claims if claim_is_supported(claim, contexts)) / len(claims)


def citation_correctness(claims: Sequence[RAGClaim], contexts: Sequence[RAGContext]) -> float:
    available = {context.source_id for context in contexts}
    citations = 0
    correct = 0
    for claim in claims:
        for source_id in claim.cited_source_ids:
            citations += 1
            if source_id in available and source_id in claim.supported_by_source_ids:
                correct += 1
    if citations == 0:
        return 1.0 if not any(claim.requires_citation for claim in claims) else 0.0
    return correct / citations


def citation_completeness(claims: Sequence[RAGClaim], contexts: Sequence[RAGContext]) -> float:
    required_claims = [claim for claim in claims if claim.requires_citation]
    if not required_claims:
        return 1.0
    available = {context.source_id for context in contexts}
    complete = 0
    for claim in required_claims:
        if any(source_id in available and source_id in claim.supported_by_source_ids for source_id in claim.cited_source_ids):
            complete += 1
    return complete / len(required_claims)


def score_observation(observation: RAGObservation) -> RAGCaseMetrics:
    return RAGCaseMetrics(
        case_id=observation.case_id,
        repeat=observation.repeat,
        context_precision=context_precision(observation.contexts),
        context_recall=context_recall(observation.contexts, observation.required_source_ids),
        relevance=answer_relevance(observation.question, observation.answer, observation.reference_answer),
        faithfulness=faithfulness(observation.claims, observation.contexts),
        citation_correctness=citation_correctness(observation.claims, observation.contexts),
        citation_completeness=citation_completeness(observation.claims, observation.contexts),
    )


def summarize_metrics(metrics: Iterable[RAGCaseMetrics]) -> dict[str, float | int]:
    rows = list(metrics)
    fields = (
        "context_precision",
        "context_recall",
        "relevance",
        "faithfulness",
        "citation_correctness",
        "citation_completeness",
    )
    result: dict[str, float | int] = {"case_observations": len(rows)}
    for name in fields:
        values = [float(getattr(row, name)) for row in rows]
        result[name] = statistics.fmean(values) if values else 0.0
    result["aggregate_score"] = statistics.fmean(float(result[name]) for name in fields) if rows else 0.0
    return result


def run_optional_model_judge(
    observation: RAGObservation,
    *,
    enabled: bool,
    spec: JudgeSpec,
    judge: JudgeCallable | None = None,
) -> dict[str, Any]:
    manifest = spec.manifest()
    if not enabled:
        return {"enabled": False, "executed": False, "judge": manifest}
    if judge is None:
        raise ValueError("judge callable is required when model judging is enabled")
    deterministic = score_observation(observation)
    request = JudgeRequest(
        case_id=observation.case_id,
        question=observation.question,
        answer=observation.answer,
        contexts=observation.contexts,
        deterministic_scores={
            "context_precision": deterministic.context_precision,
            "context_recall": deterministic.context_recall,
            "relevance": deterministic.relevance,
            "faithfulness": deterministic.faithfulness,
            "citation_correctness": deterministic.citation_correctness,
            "citation_completeness": deterministic.citation_completeness,
        },
        spec=spec,
    )
    result = judge(request)
    score = min(1.0, max(0.0, float(result.score)))
    return {
        "enabled": True,
        "executed": True,
        "judge": manifest,
        "score": score,
        "rationale": result.rationale,
        "raw": result.raw,
    }


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


def calibrate_model_judge(
    examples: Sequence[JudgeCalibrationExample],
    *,
    spec: JudgeSpec,
    max_mae: float = 0.10,
    min_correlation: float = 0.90,
) -> dict[str, Any]:
    if not examples:
        raise ValueError("at least one calibration example is required")
    deterministic = [min(1.0, max(0.0, item.deterministic_score)) for item in examples]
    judged = [min(1.0, max(0.0, item.judge_score)) for item in examples]
    errors = [judge - truth for truth, judge in zip(deterministic, judged)]
    mae = statistics.fmean(abs(value) for value in errors)
    bias = statistics.fmean(errors)
    correlation = _pearson(deterministic, judged)
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
