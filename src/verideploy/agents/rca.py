from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from statistics import fmean
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from verideploy.rag.fusion.schemas import EvidenceChannel, NormalizedEvidence
from .base import BaseAgent
from .contracts import AgentAuthorization, AgentName, AgentRequest, ToolBudget, ToolPermission


class RCAHypothesisKind(StrEnum):
    ROOT_CAUSE = "root_cause"
    TRIGGER = "trigger"
    ALTERNATIVE = "alternative"


class RCACausalRelation(StrEnum):
    PRECEDES = "precedes"
    CORRELATES = "correlates"
    DEPENDS_ON = "depends_on"


class RCACausalLink(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_evidence_id: UUID
    target_evidence_id: UUID
    relation: RCACausalRelation
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("source_evidence_id", "target_evidence_id", mode="before")
    @classmethod
    def decode_uuid(cls, value):
        return UUID(value) if isinstance(value, str) else value

    @field_validator("relation", mode="before")
    @classmethod
    def decode_relation(cls, value):
        return RCACausalRelation(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def distinct_nodes(self) -> "RCACausalLink":
        if self.source_evidence_id == self.target_evidence_id:
            raise ValueError("causal link endpoints must differ")
        return self


class RCARecommendedTest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    test_id: str = Field(pattern=r"^test-[0-9]{2}$")
    objective: str = Field(min_length=1, max_length=2000)
    expected_if_true: str = Field(min_length=1, max_length=2000)
    expected_if_false: str = Field(min_length=1, max_length=2000)
    risk: Literal["read_only", "requires_approval"] = "read_only"


class RCAHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    hypothesis_id: str = Field(pattern=r"^hyp-[0-9]{2}$")
    rank: int = Field(ge=1, le=8)
    kind: RCAHypothesisKind
    statement: str = Field(min_length=1, max_length=5000)
    model_confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[UUID] = Field(min_length=1, max_length=32)
    disconfirming_evidence_ids: list[UUID] = Field(default_factory=list, max_length=32)
    causal_links: list[RCACausalLink] = Field(default_factory=list, max_length=32)
    temporal_rationale: str = Field(min_length=1, max_length=3000)
    recommended_tests: list[RCARecommendedTest] = Field(default_factory=list, max_length=5)

    @field_validator("supporting_evidence_ids", "disconfirming_evidence_ids", mode="before")
    @classmethod
    def decode_evidence_ids(cls, value):
        return [UUID(item) if isinstance(item, str) else item for item in (value or [])]

    @field_validator("kind", mode="before")
    @classmethod
    def decode_kind(cls, value):
        return RCAHypothesisKind(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def evidence_sets_are_valid(self) -> "RCAHypothesis":
        if len(set(self.supporting_evidence_ids)) != len(self.supporting_evidence_ids):
            raise ValueError("duplicate supporting evidence IDs")
        if len(set(self.disconfirming_evidence_ids)) != len(self.disconfirming_evidence_ids):
            raise ValueError("duplicate disconfirming evidence IDs")
        if set(self.supporting_evidence_ids) & set(self.disconfirming_evidence_ids):
            raise ValueError("supporting and disconfirming evidence must not overlap")
        support = set(self.supporting_evidence_ids)
        if any(link.source_evidence_id not in support or link.target_evidence_id not in support for link in self.causal_links):
            raise ValueError("causal links must connect supporting evidence")
        if len({item.test_id for item in self.recommended_tests}) != len(self.recommended_tests):
            raise ValueError("duplicate recommended test IDs")
        return self


class RCAProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    incident_summary: str = Field(min_length=1, max_length=8000)
    hypotheses: list[RCAHypothesis] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def ranked_unique_hypotheses(self) -> "RCAProposal":
        ids = [item.hypothesis_id for item in self.hypotheses]
        ranks = [item.rank for item in self.hypotheses]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate RCA hypothesis IDs")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("RCA hypothesis ranks must be contiguous and ordered")
        return self


class RCAHypothesisAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis_id: str
    rank: int
    kind: RCAHypothesisKind
    statement: str
    model_confidence: float = Field(ge=0, le=1)
    adjusted_confidence: float = Field(ge=0, le=1)
    support_count: int = Field(ge=1)
    contradiction_count: int = Field(ge=0)
    supporting_channels: list[EvidenceChannel]
    temporal_score: float = Field(ge=0, le=1)
    causal_score: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[UUID]
    disconfirming_evidence_ids: list[UUID]
    causal_links: list[RCACausalLink]
    temporal_rationale: str
    recommended_tests: list[RCARecommendedTest]


class RCASufficiency(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_cause_determined: bool
    top_hypothesis_id: str | None = None
    evidence_count: int = Field(ge=0)
    evidence_channels: list[EvidenceChannel]
    reason_codes: list[str]


class RCAAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_summary: str
    hypotheses: list[RCAHypothesisAssessment]
    root_causes: list[RCAHypothesisAssessment]
    triggers: list[RCAHypothesisAssessment]
    alternatives: list[RCAHypothesisAssessment]
    limitations: list[str]
    sufficiency: RCASufficiency
    tool_calls_used: int = Field(default=0, ge=0, le=64)


class RCAAgent(BaseAgent[RCAProposal]):
    model_name="role:reasoning"; reasoning_setting="high"
    agent_name = AgentName.RCA
    prompt_name = "rca"
    prompt_version = "1.0.0"
    output_model = RCAProposal
    schema_name = "agent_rca_proposal"

    async def run(
        self,
        request: AgentRequest,
        *,
        authorization: AgentAuthorization,
        evidence: list[NormalizedEvidence],
        min_root_support: int = 2,
        min_root_confidence: float = 0.55,
        required_channels: list[EvidenceChannel] | None = None,
        max_evidence: int = 40,
    ) -> RCAAgentResult:
        authorization.require([ToolPermission.RCA_ANALYSIS_READ])
        if not evidence:
            raise ValueError("RCA requires evidence")
        if len(evidence) > max_evidence:
            raise ValueError("RCA evidence exceeds configured maximum")
        if len({item.evidence_id for item in evidence}) != len(evidence):
            raise ValueError("RCA evidence IDs must be unique")
        if any(item.tenant_id != request.tenant_id for item in evidence):
            raise PermissionError("RCA evidence tenant must match request tenant")
        self._validate_trusted_scope(request, evidence)

        evidence_map = {item.evidence_id: item for item in evidence}
        compact = [
            {
                "evidence_id": str(item.evidence_id),
                "channel": item.channel.value,
                "title": item.title,
                "content": item.content,
                "source_system": item.source_system,
                "source_id": item.source_id,
                "source_confidence": item.source_confidence,
                "relevance_score": item.relevance_score,
                "timestamp": item.locator.timestamp.isoformat() if item.locator.timestamp else None,
                "provenance": item.provenance,
            }
            for item in evidence
        ]
        proposal, run = await self._generate(
            request,
            authorization=authorization,
            budget=ToolBudget(max_calls=0),
            payload={
                "objective": request.objective,
                "context": request.context,
                "evidence": compact,
                "allowed_kinds": [item.value for item in RCAHypothesisKind],
                "max_hypotheses": 8,
                "required_root_support": min_root_support,
            },
        )
        try:
            assessments = [self._assess(item, evidence_map) for item in proposal.hypotheses]
            roots = [item for item in assessments if item.kind is RCAHypothesisKind.ROOT_CAUSE]
            triggers = [item for item in assessments if item.kind is RCAHypothesisKind.TRIGGER]
            alternatives = [item for item in assessments if item.kind is RCAHypothesisKind.ALTERNATIVE]
            channels = sorted({item.channel for item in evidence}, key=lambda item: item.value)
            reasons: list[str] = []
            required = set(required_channels or [])
            if required - set(channels):
                reasons.append("required_evidence_channel_missing")
            qualified = [item for item in roots if item.support_count >= min_root_support and item.adjusted_confidence >= min_root_confidence]
            if not roots:
                reasons.append("no_root_cause_hypothesis")
            elif not qualified:
                reasons.append("root_cause_support_or_confidence_insufficient")
            if roots and all(item.contradiction_count > 0 for item in roots):
                reasons.append("root_cause_has_disconfirming_evidence")
            determined = not reasons and bool(qualified)
            top = qualified[0].hypothesis_id if determined else None
            result = RCAAgentResult(
                incident_summary=proposal.incident_summary,
                hypotheses=assessments,
                root_causes=roots,
                triggers=triggers,
                alternatives=alternatives,
                limitations=proposal.limitations,
                sufficiency=RCASufficiency(
                    root_cause_determined=determined,
                    top_hypothesis_id=top,
                    evidence_count=len(evidence),
                    evidence_channels=channels,
                    reason_codes=reasons or ["sufficient"],
                ),
            )
            self.repository.complete(
                tenant_id=request.tenant_id,
                run_id=run.run_id,
                output=result.model_dump(mode="json"),
                tool_calls_used=0,
            )
            return result
        except Exception as exc:
            self.repository.fail(
                tenant_id=request.tenant_id,
                run_id=run.run_id,
                error_code=type(exc).__name__,
                tool_calls_used=0,
            )
            raise

    @staticmethod
    def _validate_trusted_scope(request: AgentRequest, evidence: list[NormalizedEvidence]) -> None:
        for item in evidence:
            for key in ("service", "environment"):
                trusted = request.context.get(key)
                observed = item.provenance.get(key)
                if trusted is not None and observed is not None and str(observed) != str(trusted):
                    raise PermissionError(f"RCA evidence {key} cannot broaden trusted request scope")

    @staticmethod
    def _assess(hypothesis: RCAHypothesis, evidence_map: dict[UUID, NormalizedEvidence]) -> RCAHypothesisAssessment:
        referenced = set(hypothesis.supporting_evidence_ids) | set(hypothesis.disconfirming_evidence_ids)
        for link in hypothesis.causal_links:
            referenced.add(link.source_evidence_id)
            referenced.add(link.target_evidence_id)
        unknown = sorted(str(item) for item in referenced - set(evidence_map))
        if unknown:
            raise ValueError("RCA hypothesis references unknown evidence IDs: " + ", ".join(unknown))

        support = [evidence_map[item] for item in hypothesis.supporting_evidence_ids]
        contradiction = [evidence_map[item] for item in hypothesis.disconfirming_evidence_ids]
        support_quality = fmean(item.source_confidence * item.relevance_score for item in support)
        contradiction_penalty = min(0.6, 0.2 * len(contradiction))
        temporal_score = RCAAgent._temporal_score(support)
        causal_score = min(1.0, len(hypothesis.causal_links) / max(1, len(support) - 1)) if len(support) > 1 else (1.0 if hypothesis.causal_links else 0.5)
        evidence_score = 0.5 * support_quality + 0.25 * temporal_score + 0.25 * causal_score
        adjusted = max(0.0, min(hypothesis.model_confidence, evidence_score) - contradiction_penalty)
        channels = sorted({item.channel for item in support}, key=lambda item: item.value)
        return RCAHypothesisAssessment(
            hypothesis_id=hypothesis.hypothesis_id,
            rank=hypothesis.rank,
            kind=hypothesis.kind,
            statement=hypothesis.statement,
            model_confidence=hypothesis.model_confidence,
            adjusted_confidence=round(adjusted, 6),
            support_count=len(support),
            contradiction_count=len(contradiction),
            supporting_channels=channels,
            temporal_score=round(temporal_score, 6),
            causal_score=round(causal_score, 6),
            supporting_evidence_ids=hypothesis.supporting_evidence_ids,
            disconfirming_evidence_ids=hypothesis.disconfirming_evidence_ids,
            causal_links=hypothesis.causal_links,
            temporal_rationale=hypothesis.temporal_rationale,
            recommended_tests=hypothesis.recommended_tests,
        )

    @staticmethod
    def _temporal_score(evidence: list[NormalizedEvidence]) -> float:
        times: list[datetime] = [item.locator.timestamp for item in evidence if item.locator.timestamp is not None]
        if not times:
            return 0.5
        if len(times) == 1:
            return 0.7
        span = (max(times) - min(times)).total_seconds()
        if span <= 300:
            return 1.0
        if span <= 1800:
            return 0.85
        if span <= 7200:
            return 0.65
        return 0.4
