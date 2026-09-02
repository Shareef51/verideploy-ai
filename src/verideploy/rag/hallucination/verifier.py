from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .schemas import EvidenceVerification

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:/-]*")
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I),
    re.compile(r"reveal\s+(?:the\s+)?system\s+prompt", re.I),
    re.compile(r"(?:bypass|disable)\s+(?:authorization|guardrails|security)", re.I),
    re.compile(r"execute\s+(?:the\s+)?tool\s+without\s+(?:approval|authorization)", re.I),
    re.compile(r"(?:api[_ -]?key|password|secret|token)\s*[:=]", re.I),
)
_NEGATION = {"not", "no", "never", "without", "failed", "failure", "false", "denied", "disabled", "unavailable"}
_STOPWORDS = {"a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "of", "and", "or", "in", "on", "for", "with", "that", "this", "it", "as", "by", "from", "at"}


@dataclass(frozen=True)
class SanitizedEvidence:
    text: str
    ignored_lines: tuple[str, ...]


def sanitize_evidence(text: str) -> SanitizedEvidence:
    safe: list[str] = []
    ignored: list[str] = []
    for line in text.splitlines() or [text]:
        normalized = line.strip()
        if normalized and any(p.search(normalized) for p in _INJECTION_PATTERNS):
            ignored.append(normalized[:500])
        else:
            safe.append(line)
    return SanitizedEvidence(text="\n".join(safe).strip(), ignored_lines=tuple(ignored))


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.casefold()) if t not in _STOPWORDS and len(t) > 1}


def lexical_entailment(claim: str, evidence: str) -> float:
    claim_tokens = _tokens(claim)
    if not claim_tokens:
        return 0.0
    ev = _tokens(evidence)
    return min(1.0, len(claim_tokens & ev) / len(claim_tokens))


def contradiction_score(claim: str, evidence: str) -> float:
    claim_tokens = _tokens(claim)
    ev_tokens = _tokens(evidence)
    overlap = claim_tokens & ev_tokens
    if not overlap:
        return 0.0
    claim_neg = bool(claim_tokens & _NEGATION)
    ev_neg = bool(ev_tokens & _NEGATION)
    if claim_neg != ev_neg and len(overlap) >= max(1, len(claim_tokens) // 3):
        return min(1.0, 0.65 + 0.35 * (len(overlap) / max(1, len(claim_tokens))))
    # Explicit contradiction vocabulary around a common subject.
    contrary_pairs = (("enabled", "disabled"), ("available", "unavailable"), ("success", "failed"), ("approved", "denied"), ("increase", "decrease"), ("healthy", "unhealthy"))
    for left, right in contrary_pairs:
        if (left in claim_tokens and right in ev_tokens) or (right in claim_tokens and left in ev_tokens):
            return 0.9
    return 0.0


def verify_evidence(*, chunk_id, claim: str, content: str) -> EvidenceVerification:
    sanitized = sanitize_evidence(content)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return EvidenceVerification(
        chunk_id=chunk_id,
        evidence_sha256=digest,
        lexical_entailment=lexical_entailment(claim, sanitized.text),
        contradiction_score=contradiction_score(claim, sanitized.text),
        prompt_injection_detected=bool(sanitized.ignored_lines),
        ignored_instruction_lines=sanitized.ignored_lines,
    )
