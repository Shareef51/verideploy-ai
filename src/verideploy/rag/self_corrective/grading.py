from __future__ import annotations

from verideploy.rag.orchestration.schemas import RetrievalPipelineResult
from .schemas import EvidenceGrade, EvidenceGradeResult


def grade_evidence(result: RetrievalPipelineResult) -> EvidenceGradeResult:
    candidates = result.candidates
    source_count = len({item.source_key for item in candidates})
    top = max((item.rerank_score for item in candidates), default=0.0)
    context_count = len(result.context)
    # Transparent deterministic rubric: relevance + corroboration + usable context.
    relevance = min(1.0, top)
    corroboration = min(1.0, source_count / 2.0)
    context = min(1.0, context_count / 2.0)
    score = round((0.55 * relevance) + (0.25 * corroboration) + (0.20 * context), 8)
    reasons: list[str] = []
    if not candidates:
        reasons.append("no_candidates")
    if top < 0.45:
        reasons.append("low_top_relevance")
    if source_count < 2:
        reasons.append("insufficient_source_corroboration")
    if context_count == 0:
        reasons.append("no_usable_context")
    if candidates and top >= 0.58 and source_count >= 2 and context_count >= 2 and score >= 0.60:
        grade = EvidenceGrade.SUFFICIENT
    elif candidates and context_count and score >= 0.34:
        grade = EvidenceGrade.WEAK
    else:
        grade = EvidenceGrade.INSUFFICIENT
    return EvidenceGradeResult(
        grade=grade, score=score, candidate_count=len(candidates), source_count=source_count,
        context_count=context_count, top_rerank_score=round(top, 8), reasons=tuple(reasons),
    )
