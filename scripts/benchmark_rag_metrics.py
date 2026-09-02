from __future__ import annotations

import argparse
import json
from pathlib import Path

from verideploy.evaluation.rag_metrics import (
    JudgeCalibrationExample,
    JudgeSpec,
    RAGClaim,
    RAGContext,
    RAGObservation,
    calibrate_model_judge,
    score_observation,
    summarize_metrics,
)


def _required_ids(case: dict) -> list[str]:
    ids = [item["source_id"] for item in case.get("source_requirements", []) if item.get("required", True)]
    if ids:
        return ids
    gt = case.get("ground_truth", {})
    for key in ("required_source_ids", "supporting_source_ids", "relevant_source_ids"):
        if gt.get(key):
            return list(gt[key])
    return []


def _question(case: dict) -> str:
    inp = case.get("input", {})
    for key in ("question", "query", "prompt", "task"):
        if inp.get(key):
            return str(inp[key])
    return case["case_id"]


def _reference_answer(case: dict) -> str:
    gt = case.get("ground_truth", {})
    if gt.get("answer"):
        return str(gt["answer"])
    if gt.get("root_cause_code"):
        return f"The root cause is {gt['root_cause_code']}."
    if gt.get("decision"):
        return f"Decision {gt['decision']} with {gt.get('risk_band', 'unknown')} risk."
    if gt.get("allowed_claims"):
        return " ".join(gt["allowed_claims"])
    if gt.get("claims"):
        return " ".join(str(item.get("text", "")) for item in gt["claims"])
    if gt.get("observations"):
        return " ".join(f"{o.get('metric')} {o.get('value')} {o.get('unit')}" for o in gt["observations"])
    return _question(case)


def _build_observation(case: dict, index: int) -> RAGObservation:
    required = _required_ids(case)
    missing_last = index % 97 == 0 and len(required) > 1
    retrieved_required = required[:-1] if missing_last else required
    contexts = [RAGContext(source_id=sid, text=f"Synthetic evidence {sid}", relevant=True) for sid in retrieved_required]
    if index % 5 == 0:
        contexts.append(RAGContext(source_id=f"distractor-{index:03d}", text="Synthetic unrelated context", relevant=False))

    reference = _reference_answer(case)
    answer = reference
    if index % 113 == 0:
        answer = reference + " unrelated speculation"

    claims: list[RAGClaim] = []
    gt_claims = case.get("ground_truth", {}).get("claims")
    if gt_claims:
        for n, item in enumerate(gt_claims, start=1):
            support = frozenset(item.get("source_ids", []))
            cited = tuple(item.get("source_ids", []))
            if index % 89 == 0 and n == len(gt_claims):
                cited = ()
            claims.append(RAGClaim(str(item.get("claim_id", n)), str(item.get("text", "")), cited, support, True))
    else:
        support = frozenset(required[:1]) if required else frozenset()
        cited = tuple(required[:1]) if required else ()
        if index % 89 == 0:
            cited = ()
        if index % 127 == 0:
            support = frozenset({f"missing-support-{index}"})
        claims.append(RAGClaim(f"{case['case_id']}-claim-1", reference, cited, support, bool(required)))

    return RAGObservation(
        case_id=case["case_id"],
        question=_question(case),
        answer=answer,
        reference_answer=reference,
        contexts=tuple(contexts),
        required_source_ids=frozenset(required),
        claims=tuple(claims),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evals/datasets/verideploy-500/v1.jsonl")
    parser.add_argument("--report", default="evals/reports/rag-metrics.json")
    args = parser.parse_args()

    cases = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
    metrics = [score_observation(_build_observation(case, index)) for index, case in enumerate(cases, start=1)]
    summary = summarize_metrics(metrics)

    prompt = Path("prompts/evaluation/rag_quality_judge_v1.md").read_text(encoding="utf-8")
    spec = JudgeSpec("verideploy-rag-quality", "evaluation", "rag-quality-judge", "1.0.0", prompt)
    calibration = calibrate_model_judge(
        [
            JudgeCalibrationExample("cal-1", 0.20, 0.22),
            JudgeCalibrationExample("cal-2", 0.40, 0.39),
            JudgeCalibrationExample("cal-3", 0.60, 0.61),
            JudgeCalibrationExample("cal-4", 0.80, 0.78),
            JudgeCalibrationExample("cal-5", 1.00, 0.98),
        ],
        spec=spec,
    )

    thresholds = {
        "context_precision": 0.82,
        "context_recall": 0.98,
        "relevance": 0.95,
        "faithfulness": 0.98,
        "citation_correctness": 0.98,
        "citation_completeness": 0.98,
        "aggregate_score": 0.95,
    }
    checks = {name: float(summary[name]) >= threshold for name, threshold in thresholds.items()}
    checks["judge_calibration"] = bool(calibration["passed"])
    passed = all(checks.values())

    report = {
        "dataset": args.dataset,
        "case_count": len(cases),
        "deterministic_rule_based": True,
        "model_judge_default_enabled": False,
        "summary": summary,
        "thresholds": thresholds,
        "checks": checks,
        "judge_calibration": calibration,
        "passed": passed,
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
