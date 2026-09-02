from __future__ import annotations

from uuid import uuid4

from verideploy.rag.self_corrective.repository import SelfCorrectiveRunRepository
from .repository import HallucinationProtectionRepository
from .schemas import (
    ClaimReleaseAction, ClaimSupportLabel, HallucinationProtectionRequest,
    HallucinationProtectionResult, VerifiedClaim,
)
from .verifier import verify_evidence

VERIFIER_VERSION = "1.0.0"


class HallucinationProtector:
    def __init__(self, *, source_runs: SelfCorrectiveRunRepository, repository: HallucinationProtectionRepository,
                 supported_threshold: float = 0.68, uncertain_threshold: float = 0.42,
                 contradiction_threshold: float = 0.65, protected_unsupported_material_threshold: float = 0.05) -> None:
        if not (0 <= uncertain_threshold <= supported_threshold <= 1):
            raise ValueError("invalid hallucination support thresholds")
        self.source_runs = source_runs
        self.repository = repository
        self.supported_threshold = supported_threshold
        self.uncertain_threshold = uncertain_threshold
        self.contradiction_threshold = contradiction_threshold
        self.protected_unsupported_material_threshold = protected_unsupported_material_threshold

    def protect(self, request: HallucinationProtectionRequest) -> HallucinationProtectionResult:
        source = self.source_runs.get(tenant_id=request.tenant_id, run_id=request.self_corrective_run_id)
        if source is None:
            raise LookupError("self-corrective RAG run not found in tenant scope")
        evidence_map = {ctx.chunk_id: ctx for ctx in source.final_retrieval.context}
        verified: list[VerifiedClaim] = []
        injection_count = 0

        for claim in request.claims:
            reasons: list[str] = []
            checks = []
            for chunk_id in claim.evidence_chunk_ids:
                context = evidence_map.get(chunk_id)
                if context is None:
                    reasons.append("citation_not_in_source_run")
                    continue
                check = verify_evidence(chunk_id=chunk_id, claim=claim.text, content=context.content)
                checks.append(check)
                if check.prompt_injection_detected:
                    injection_count += 1
                    reasons.append("prompt_injection_text_ignored")

            max_entailment = max((x.lexical_entailment for x in checks), default=0.0)
            max_contradiction = max((x.contradiction_score for x in checks), default=0.0)
            if not claim.evidence_chunk_ids:
                reasons.append("claim_has_no_evidence")
            if not checks and claim.evidence_chunk_ids:
                reasons.append("no_valid_cited_evidence")

            adjusted = min(claim.proposed_confidence, max_entailment)
            if max_contradiction >= self.contradiction_threshold:
                adjusted = min(adjusted, 0.15)
                label = ClaimSupportLabel.UNSUPPORTED
                reasons.append("cited_evidence_contradicts_claim")
            elif max_entailment >= self.supported_threshold:
                label = ClaimSupportLabel.SUPPORTED
                reasons.append("cited_evidence_entails_claim")
            elif max_entailment >= self.uncertain_threshold:
                label = ClaimSupportLabel.UNCERTAIN
                reasons.append("cited_evidence_partially_supports_claim")
            else:
                label = ClaimSupportLabel.UNSUPPORTED
                reasons.append("cited_evidence_does_not_support_claim")

            if label is ClaimSupportLabel.SUPPORTED:
                action = ClaimReleaseAction.KEEP
                released = claim.text
            elif label is ClaimSupportLabel.UNCERTAIN:
                action = ClaimReleaseAction.QUALIFY
                released = f"Evidence is incomplete: {claim.text}"
            else:
                action = ClaimReleaseAction.REMOVE
                released = None
            verified.append(VerifiedClaim(
                claim_id=claim.claim_id, original_text=claim.text, released_text=released, label=label,
                action=action, material=claim.material, proposed_confidence=claim.proposed_confidence,
                adjusted_confidence=round(adjusted, 6), evidence=tuple(checks), reasons=tuple(dict.fromkeys(reasons)),
            ))

        supported = sum(c.label is ClaimSupportLabel.SUPPORTED for c in verified)
        uncertain = sum(c.label is ClaimSupportLabel.UNCERTAIN for c in verified)
        unsupported = sum(c.label is ClaimSupportLabel.UNSUPPORTED for c in verified)
        material = [c for c in verified if c.material]
        proposed_unsupported_material = [c for c in material if c.label is ClaimSupportLabel.UNSUPPORTED]
        proposed_unsupported_rate = len(proposed_unsupported_material) / len(material) if material else 0.0
        released_material = [c for c in material if c.released_text]
        released_unsupported_material = [c for c in released_material if c.label is ClaimSupportLabel.UNSUPPORTED]
        unsupported_rate = len(released_unsupported_material) / len(released_material) if released_material else 0.0
        released_lines = [c.released_text for c in verified if c.released_text]
        protected_answer = "\n".join(released_lines) if released_lines else (
            "Insufficient supported evidence to release a material answer. Unsupported claims were removed."
        )
        result = HallucinationProtectionResult(
            verification_id=uuid4(), tenant_id=request.tenant_id, self_corrective_run_id=request.self_corrective_run_id,
            verifier_version=VERIFIER_VERSION, protected=unsupported_rate <= self.protected_unsupported_material_threshold,
            protected_answer=protected_answer, claims=verified, supported_count=supported, uncertain_count=uncertain,
            unsupported_count=unsupported, unsupported_material_rate=round(unsupported_rate, 6),
            prompt_injection_evidence_count=injection_count,
            metadata={
                "supported_threshold": self.supported_threshold,
                "uncertain_threshold": self.uncertain_threshold,
                "contradiction_threshold": self.contradiction_threshold,
                "protected_unsupported_material_threshold": self.protected_unsupported_material_threshold,
                "source_answerable": source.answerable,
                "proposed_unsupported_material_rate": round(proposed_unsupported_rate, 6),
                "removed_unsupported_material_count": len(proposed_unsupported_material),
            },
        )
        self.repository.save(result)
        return result

    def get(self, *, tenant_id, verification_id):
        return self.repository.get(tenant_id=tenant_id, verification_id=verification_id)
