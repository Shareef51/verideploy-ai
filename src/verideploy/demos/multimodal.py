from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DemoEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(pattern=r"^ev-[a-z0-9-]+$")
    citation_id: str = Field(pattern=r"^cit-[a-z0-9-]+$")
    label: str = Field(min_length=3, max_length=160)
    asset: str = Field(min_length=3)
    modality: Literal["document", "image", "video", "audio"]


class DemoExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_cause: str = Field(min_length=10)
    confidence: float = Field(ge=0, le=1)
    critic_status: str = Field(min_length=3)
    decision: str = Field(min_length=3)
    review_status: Literal["pending", "approved", "rejected"]
    latency_budget_ms: int = Field(gt=0)
    estimated_cost_usd: float = Field(ge=0)
    required_citations: tuple[str, ...] = Field(min_length=1)


class MultimodalDemoManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    id: Literal["multimodal-killer"]
    title: str
    synthetic: Literal[True]
    one_click: Literal[True]
    workspace_href: str
    incident_id: str
    release_id: str
    evidence: tuple[DemoEvidence, ...] = Field(min_length=7)
    graph: tuple[str, ...] = Field(min_length=7)
    expected: DemoExpected

    @model_validator(mode="after")
    def consistent(self) -> "MultimodalDemoManifest":
        evidence_ids = [item.evidence_id for item in self.evidence]
        citation_ids = [item.citation_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        if len(citation_ids) != len(set(citation_ids)):
            raise ValueError("citation IDs must be unique")
        if set(self.expected.required_citations) != set(citation_ids):
            raise ValueError("required citations must exactly cover demo evidence")
        required_nodes = {"multimodal_extraction", "incident_rca", "rca_critic", "human_review_gate"}
        if not required_nodes.issubset(self.graph):
            raise ValueError("graph is missing required multimodal/review nodes")
        return self

    @classmethod
    def load(cls, root: Path) -> "MultimodalDemoManifest":
        return cls.model_validate(json.loads((root / "config/demos/multimodal-killer-demo.json").read_text()))


def validate_multimodal_demo(root: Path) -> dict[str, object]:
    manifest = MultimodalDemoManifest.load(root)
    issues: list[str] = []
    for item in manifest.evidence:
        path = root / item.asset
        if not path.is_file():
            issues.append(f"missing asset: {item.asset}")
            continue
        data = path.read_bytes()[:16]
        if item.modality == "image" and not data.startswith(b"\x89PNG"):
            issues.append(f"invalid image signature: {item.asset}")
        if item.modality == "video" and data[4:8] != b"ftyp":
            issues.append(f"invalid video signature: {item.asset}")
        if item.modality == "document" and path.suffix.lower() == ".pdf" and not data.startswith(b"%PDF-"):
            issues.append(f"invalid pdf signature: {item.asset}")
    return {
        "gate": "pass" if not issues else "fail",
        "synthetic": manifest.synthetic,
        "evidence_count": len(manifest.evidence),
        "citation_count": len(manifest.expected.required_citations),
        "graph_nodes": list(manifest.graph),
        "critic_status": manifest.expected.critic_status,
        "review_status": manifest.expected.review_status,
        "latency_budget_ms": manifest.expected.latency_budget_ms,
        "estimated_cost_usd": manifest.expected.estimated_cost_usd,
        "issues": issues,
    }
