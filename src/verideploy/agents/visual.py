from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from verideploy.multimodal.image_intelligence import (
    EvidenceLocator,
    ImageAnalysisType,
    VisualAnalysisResult,
)
from verideploy.rag.visual_retrieval.schemas import VisualSearchHit, VisualSearchQuery

from .base import BaseAgent
from .contracts import AgentAuthorization, AgentName, AgentRequest, ToolBudget, ToolPermission
from .visual_tools import VisualAnalysisPort, VisualSearchPort


class VisualIntent(StrEnum):
    SCREENSHOT = "screenshot"
    ARCHITECTURE = "architecture"
    DASHBOARD = "dashboard"


class VisualQueryAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    normalized_query: str = Field(min_length=1, max_length=4_000)
    intent: VisualIntent
    analysis_type: ImageAnalysisType
    top_k: int = Field(default=3, ge=1, le=5)
    document_id: UUID | None = None
    rationale: str = Field(min_length=1, max_length=4_000)

    @field_validator("intent", "analysis_type", mode="before")
    @classmethod
    def decode_enums(cls, value, info):
        enum_type = VisualIntent if info.field_name == "intent" else ImageAnalysisType
        return enum_type(value) if isinstance(value, str) else value

    @field_validator("document_id", mode="before")
    @classmethod
    def decode_document_id(cls, value):
        return UUID(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def intent_matches_analysis(self) -> "VisualQueryAnalysis":
        expected = {
            VisualIntent.ARCHITECTURE: ImageAnalysisType.ARCHITECTURE,
            VisualIntent.DASHBOARD: ImageAnalysisType.DASHBOARD,
            VisualIntent.SCREENSHOT: ImageAnalysisType.ERROR_SCREEN,
        }[self.intent]
        if self.analysis_type != expected:
            raise ValueError("visual intent must use its matching analysis_type")
        return self


class VisualEvidenceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: str
    statement: str
    confidence: float = Field(ge=0, le=1)
    locator: EvidenceLocator | None = None


class VisualDerivedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["inference", "dashboard_anomaly", "architecture_component", "architecture_relationship", "error_signal"]
    statement: str = Field(min_length=1, max_length=4000)
    based_on_observation_ids: list[str] = Field(min_length=1, max_length=30)
    confidence: float | None = Field(default=None, ge=0, le=1)
    severity: str | None = Field(default=None, max_length=32)


class VisualEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    page_id: UUID
    document_id: UUID
    page_number: int = Field(ge=1)
    image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    analysis_type: ImageAnalysisType
    summary: str
    observations: list[VisualEvidenceObservation]
    derived_findings: list[VisualDerivedFinding]
    limitations: list[str]
    confidence_score: float = Field(ge=0, le=1)
    confidence_level: Literal["high", "moderate", "low", "insufficient"]
    qualification_reasons: list[str]


class VisualEvidenceSufficiency(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sufficient: bool
    evidence_count: int = Field(ge=0)
    direct_observation_count: int = Field(ge=0)
    located_observation_count: int = Field(ge=0)
    reason_codes: list[str]


class VisualEvidenceAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis: VisualQueryAnalysis
    evidence: list[VisualEvidenceItem]
    sufficiency: VisualEvidenceSufficiency
    tool_calls_used: int = Field(ge=0, le=64)


class VisualEvidenceAgent(BaseAgent[VisualQueryAnalysis]):
    agent_name = AgentName.VISUAL_EVIDENCE
    prompt_name = "visual_evidence"
    prompt_version = "1.0.0"
    output_model = VisualQueryAnalysis
    schema_name = "agent_visual_query_analysis"

    def __init__(self, *, model, prompts, repository, search: VisualSearchPort, analyzer: VisualAnalysisPort) -> None:
        super().__init__(model=model, prompts=prompts, repository=repository)
        self.search = search
        self.analyzer = analyzer

    async def run(
        self,
        request: AgentRequest,
        *,
        authorization: AgentAuthorization,
        budget: ToolBudget,
        min_short_side: int = 720,
        min_confidence: float = 0.55,
        max_analyses: int = 3,
    ) -> VisualEvidenceAgentResult:
        authorization.require([ToolPermission.VISUAL_EVIDENCE_READ])
        analysis, run = await self._generate(
            request,
            authorization=authorization,
            budget=budget,
            payload={
                "objective": request.objective,
                "context": request.context,
                "allowed_intents": [item.value for item in VisualIntent],
                "allowed_analysis_types": [item.value for item in ImageAnalysisType],
                "max_visual_candidates": min(max_analyses, max(0, budget.max_calls - 1)),
                "tool_budget": budget.max_calls,
            },
        )
        active_budget = budget
        try:
            trusted_document_id = request.context.get("document_id")
            if trusted_document_id is not None:
                trusted_document_id = UUID(str(trusted_document_id))
                if analysis.document_id not in {None, trusted_document_id}:
                    raise PermissionError("visual document filter cannot broaden trusted request scope")
            document_id = trusted_document_id or analysis.document_id

            active_budget = active_budget.consume()
            search_result = await self.search.search(
                VisualSearchQuery(
                    tenant_id=request.tenant_id,
                    text=analysis.normalized_query,
                    top_k=min(analysis.top_k, max_analyses),
                    document_id=document_id,
                )
            )
            candidates = search_result.hits[: min(max_analyses, active_budget.remaining)]
            evidence: list[VisualEvidenceItem] = []
            analysis_failures = 0
            for hit in candidates:
                active_budget = active_budget.consume()
                try:
                    provenance, visual = await self.analyzer.analyze(
                        tenant_id=request.tenant_id,
                        correlation_id=request.correlation_id,
                        hit=hit,
                        analysis_type=analysis.analysis_type,
                    )
                except (FileNotFoundError, ValueError, RuntimeError):
                    analysis_failures += 1
                    continue
                if provenance.tenant_id != request.tenant_id:
                    raise PermissionError("visual analysis provenance tenant mismatch")
                evidence.append(
                    self._evidence(
                        request.tenant_id,
                        hit,
                        provenance,
                        visual,
                        min_short_side=min_short_side,
                        min_confidence=min_confidence,
                    )
                )

            sufficiency = self._sufficiency(
                evidence,
                had_search_hits=bool(search_result.hits),
                analysis_failures=analysis_failures,
                min_confidence=min_confidence,
            )
            result = VisualEvidenceAgentResult(
                analysis=analysis,
                evidence=evidence,
                sufficiency=sufficiency,
                tool_calls_used=active_budget.calls_used,
            )
            self.repository.complete(
                tenant_id=request.tenant_id,
                run_id=run.run_id,
                output=result.model_dump(mode="json"),
                tool_calls_used=active_budget.calls_used,
            )
            return result
        except Exception as exc:
            self.repository.fail(
                tenant_id=request.tenant_id,
                run_id=run.run_id,
                error_code=type(exc).__name__,
                tool_calls_used=active_budget.calls_used,
            )
            raise

    @staticmethod
    def _evidence(
        tenant_id: UUID,
        hit: VisualSearchHit,
        provenance,
        visual: VisualAnalysisResult,
        *,
        min_short_side: int,
        min_confidence: float,
    ) -> VisualEvidenceItem:
        observations = [
            VisualEvidenceObservation(
                observation_id=item.observation_id,
                statement=item.statement,
                confidence=item.confidence,
                locator=item.locator,
            )
            for item in visual.observations
        ]
        score = sum(item.confidence for item in observations) / len(observations) if observations else 0.0
        reasons: list[str] = []
        if min(provenance.width, provenance.height) < min_short_side:
            reasons.append("low_resolution")
        if not observations:
            reasons.append("no_direct_observations")
        if observations and not any(item.locator is not None for item in observations):
            reasons.append("missing_evidence_locators")
        if score < min_confidence:
            reasons.append("low_confidence")
        level: Literal["high", "moderate", "low", "insufficient"]
        if not observations:
            level = "insufficient"
        elif "low_resolution" in reasons or score < min_confidence:
            level = "low"
        elif score >= 0.8 and not reasons:
            level = "high"
        else:
            level = "moderate"
        derived: list[VisualDerivedFinding] = [
            VisualDerivedFinding(kind="inference", statement=item.statement, based_on_observation_ids=item.based_on_observation_ids, confidence=item.confidence)
            for item in visual.inferences
        ]
        if hasattr(visual, "anomalies"):
            derived.extend(VisualDerivedFinding(kind="dashboard_anomaly", statement=item.statement, based_on_observation_ids=item.based_on_observation_ids, severity=item.severity) for item in visual.anomalies)
        if hasattr(visual, "components"):
            derived.extend(VisualDerivedFinding(kind="architecture_component", statement=f"{item.name}" + (f" ({item.component_type})" if item.component_type else ""), based_on_observation_ids=item.based_on_observation_ids) for item in visual.components)
        if hasattr(visual, "relationships"):
            derived.extend(VisualDerivedFinding(kind="architecture_relationship", statement=f"{item.source} {item.relationship} {item.target}", based_on_observation_ids=item.based_on_observation_ids) for item in visual.relationships)
        if hasattr(visual, "errors"):
            derived.extend(VisualDerivedFinding(kind="error_signal", statement=item.message + (f" [{item.code}]" if item.code else ""), based_on_observation_ids=item.based_on_observation_ids) for item in visual.errors)
        return VisualEvidenceItem(
            evidence_id=uuid5(NAMESPACE_URL, f"{tenant_id}:visual:{hit.page_id}:{hit.image_sha256}"),
            page_id=hit.page_id,
            document_id=hit.document_id,
            page_number=hit.page_number,
            image_sha256=hit.image_sha256,
            analysis_type=visual.analysis_type,
            summary=visual.summary,
            observations=observations,
            derived_findings=derived,
            limitations=list(dict.fromkeys([*visual.limitations, *reasons])),
            confidence_score=score,
            confidence_level=level,
            qualification_reasons=reasons,
        )

    @staticmethod
    def _sufficiency(
        evidence: list[VisualEvidenceItem],
        *,
        had_search_hits: bool,
        analysis_failures: int,
        min_confidence: float,
    ) -> VisualEvidenceSufficiency:
        observations = [obs for item in evidence for obs in item.observations]
        located = [obs for obs in observations if obs.locator is not None]
        reasons: list[str] = []
        if not had_search_hits:
            reasons.append("no_visual_evidence")
        elif not evidence and analysis_failures:
            reasons.append("visual_analysis_unavailable")
        if evidence and any("low_resolution" in item.qualification_reasons for item in evidence):
            reasons.append("low_resolution")
        if not observations:
            reasons.append("no_direct_observations")
        if observations and not located:
            reasons.append("missing_evidence_locators")
        if evidence and max((item.confidence_score for item in evidence), default=0.0) < min_confidence:
            reasons.append("low_confidence")
        return VisualEvidenceSufficiency(
            sufficient=not reasons,
            evidence_count=len(evidence),
            direct_observation_count=len(observations),
            located_observation_count=len(located),
            reason_codes=reasons,
        )
