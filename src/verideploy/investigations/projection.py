from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from verideploy.investigations.schemas import InvestigationEvent, InvestigationRecord


class TimelineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    sequence_number: int
    event_type: str
    occurred_at: str
    title: str
    detail: str | None = None
    node: str | None = None
    status: str | None = None


class HypothesisView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis_id: str
    title: str
    status: str = "candidate"
    confidence: float = Field(default=0.0, ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    disconfirming_evidence_ids: list[str] = Field(default_factory=list)
    updated_sequence: int


class RootCauseView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis_id: str | None = None
    summary: str
    confidence: float = Field(default=0.0, ge=0, le=1)
    determined: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    updated_sequence: int


class EvidenceMapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    label: str
    evidence_type: str = "evidence"
    relation: str = "supports"
    hypothesis_id: str | None = None
    citation_id: str | None = None
    updated_sequence: int


class InvestigationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    investigation_id: str
    correlation_id: str
    incident_id: str | None = None
    query: str
    status: str
    cancel_requested: bool
    cancel_reason: str | None = None
    last_sequence_number: int
    updated_at: str
    timeline: list[TimelineItem] = Field(default_factory=list)
    hypotheses: list[HypothesisView] = Field(default_factory=list)
    root_cause: RootCauseView | None = None
    alternatives: list[RootCauseView] = Field(default_factory=list)
    evidence_map: list[EvidenceMapItem] = Field(default_factory=list)
    convergence_sha256: str


def _string(payload: dict[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    return str(value) if value is not None else default


def _strings(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if item is not None})


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _timeline_item(event: InvestigationEvent) -> TimelineItem:
    payload = event.payload
    node = _string(payload, "node") or None
    status = _string(payload, "status") or None
    title = _string(payload, "message") or _string(payload, "title") or event.event_type.replace(".", " ").title()
    detail = _string(payload, "detail") or _string(payload, "reason") or None
    return TimelineItem(
        event_id=str(event.event_id), sequence_number=event.sequence_number, event_type=event.event_type,
        occurred_at=event.occurred_at.isoformat(), title=title, detail=detail, node=node, status=status,
    )


def _canonical_payload_without_hash(data: dict[str, Any]) -> bytes:
    clean = dict(data)
    clean.pop("convergence_sha256", None)
    return json.dumps(clean, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()


def projection_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload_without_hash(data)).hexdigest()


def project_investigation(record: InvestigationRecord, events: list[InvestigationEvent]) -> InvestigationProjection:
    ordered = sorted(events, key=lambda item: item.sequence_number)
    hypotheses: dict[str, HypothesisView] = {}
    evidence: dict[str, EvidenceMapItem] = {}
    root_cause: RootCauseView | None = None
    alternatives: dict[str, RootCauseView] = {}

    for event in ordered:
        payload = event.payload
        if event.event_type == "investigation.hypothesis.updated":
            hypothesis_id = _string(payload, "hypothesis_id")
            title = _string(payload, "title") or _string(payload, "summary")
            if hypothesis_id and title:
                hypotheses[hypothesis_id] = HypothesisView(
                    hypothesis_id=hypothesis_id,
                    title=title,
                    status=_string(payload, "status", "candidate"),
                    confidence=_confidence(payload.get("confidence")),
                    supporting_evidence_ids=_strings(payload, "supporting_evidence_ids"),
                    disconfirming_evidence_ids=_strings(payload, "disconfirming_evidence_ids"),
                    updated_sequence=event.sequence_number,
                )
        elif event.event_type == "investigation.rca.updated":
            summary = _string(payload, "summary") or _string(payload, "root_cause")
            if summary:
                root_cause = RootCauseView(
                    hypothesis_id=_string(payload, "hypothesis_id") or None,
                    summary=summary,
                    confidence=_confidence(payload.get("confidence")),
                    determined=bool(payload.get("determined", False)),
                    evidence_ids=_strings(payload, "evidence_ids"),
                    updated_sequence=event.sequence_number,
                )
            raw_alternatives = payload.get("alternatives", [])
            if isinstance(raw_alternatives, list):
                for index, raw in enumerate(raw_alternatives):
                    if not isinstance(raw, dict):
                        continue
                    summary_alt = _string(raw, "summary") or _string(raw, "title")
                    if not summary_alt:
                        continue
                    key = _string(raw, "hypothesis_id") or f"alternative-{index}"
                    alternatives[key] = RootCauseView(
                        hypothesis_id=_string(raw, "hypothesis_id") or None,
                        summary=summary_alt,
                        confidence=_confidence(raw.get("confidence")), determined=False,
                        evidence_ids=_strings(raw, "evidence_ids"), updated_sequence=event.sequence_number,
                    )
        elif event.event_type == "investigation.evidence.linked":
            evidence_id = _string(payload, "evidence_id")
            if evidence_id:
                evidence[evidence_id] = EvidenceMapItem(
                    evidence_id=evidence_id,
                    label=_string(payload, "label") or evidence_id,
                    evidence_type=_string(payload, "evidence_type", "evidence"),
                    relation=_string(payload, "relation", "supports"),
                    hypothesis_id=_string(payload, "hypothesis_id") or None,
                    citation_id=_string(payload, "citation_id") or None,
                    updated_sequence=event.sequence_number,
                )

    payload = {
        "investigation_id": str(record.investigation_id), "correlation_id": str(record.correlation_id),
        "incident_id": record.incident_id, "query": record.query, "status": record.status.value,
        "cancel_requested": record.cancel_requested, "cancel_reason": record.cancel_reason,
        "last_sequence_number": record.last_sequence_number, "updated_at": record.updated_at.isoformat(),
        "timeline": [item.model_dump(mode="json") for item in map(_timeline_item, ordered)],
        "hypotheses": [item.model_dump(mode="json") for item in sorted(hypotheses.values(), key=lambda h: (-h.confidence, h.hypothesis_id))],
        "root_cause": root_cause.model_dump(mode="json") if root_cause else None,
        "alternatives": [item.model_dump(mode="json") for _, item in sorted(alternatives.items())],
        "evidence_map": [item.model_dump(mode="json") for _, item in sorted(evidence.items())],
    }
    payload["convergence_sha256"] = projection_hash(payload)
    return InvestigationProjection.model_validate(payload)
