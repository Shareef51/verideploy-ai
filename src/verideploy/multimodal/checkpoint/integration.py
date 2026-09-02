from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,})\b", re.I)

@dataclass(frozen=True)
class EvidenceFixture:
    evidence_id: str
    modality: str
    logical_units: int
    text: str
    fail_stage: str | None = None

@dataclass(frozen=True)
class EvidenceResult:
    evidence_id: str
    modality: str
    status: str
    trace_id: str
    storage_key: str | None
    sha256: str | None
    redacted_text: str | None
    degradation_reason: str | None
    timeline_events: int


def load_policy(root: Path) -> dict:
    return json.loads((root / "config/multimodal/checkpoint.json").read_text())


def redact(text: str) -> str:
    text = EMAIL.sub("[REDACTED_EMAIL]", text)
    return TOKEN.sub("[REDACTED_SECRET]", text)


def _limit_for(modality: str, policy: dict) -> int:
    limits = policy["limits"]
    return {
        "image": limits["max_image_megapixels"],
        "pdf": limits["max_pdf_pages"],
        "audio": limits["max_audio_minutes"],
        "video": limits["max_video_minutes"],
    }[modality]


def process_fixture(fixture: EvidenceFixture, *, tenant_id: str, policy: dict) -> EvidenceResult:
    trace_id = hashlib.sha256(f"{tenant_id}:{fixture.evidence_id}".encode()).hexdigest()[:32]
    if fixture.logical_units > _limit_for(fixture.modality, policy):
        return EvidenceResult(fixture.evidence_id, fixture.modality, "DEGRADED", trace_id, None, None, None, "bounded_limit_exceeded", 0)
    if fixture.fail_stage:
        return EvidenceResult(fixture.evidence_id, fixture.modality, "DEGRADED", trace_id, None, None, None, f"partial_failure:{fixture.fail_stage}", 0)
    safe = redact(fixture.text)
    digest = hashlib.sha256(safe.encode()).hexdigest()
    storage_key = f"tenant/{tenant_id}/multimodal/{fixture.modality}/{fixture.evidence_id}/{digest[:16]}"
    timeline_events = min(max(1, fixture.logical_units), policy["limits"]["max_timeline_events"])
    return EvidenceResult(fixture.evidence_id, fixture.modality, "READY", trace_id, storage_key, digest, safe, None, timeline_events)


def fuse(results: Iterable[EvidenceResult], *, policy: dict) -> dict:
    items = list(results)
    if len(items) > policy["limits"]["max_evidence_items"]:
        raise ValueError("evidence item limit exceeded")
    ready = [r for r in items if r.status == "READY"]
    traceable = [r for r in items if r.trace_id and (r.status != "READY" or (r.storage_key and r.sha256))]
    ratio = len(ready) / max(1, len(items))
    return {
        "status": "READY" if ratio == 1 else ("PARTIAL" if ratio >= policy["minimum_surviving_evidence_ratio"] else "FAILED"),
        "ready": len(ready),
        "total": len(items),
        "surviving_ratio": ratio,
        "traceability": len(traceable) / max(1, len(items)),
        "timeline_events": min(sum(r.timeline_events for r in ready), policy["limits"]["max_timeline_events"]),
        "degraded": [r.evidence_id for r in items if r.status != "READY"],
        "evidence_ids": [r.evidence_id for r in ready],
    }


def deterministic_fixtures(*, partial: bool = False) -> list[EvidenceFixture]:
    base = [
        EvidenceFixture("ev-image-large", "image", 40, "Grafana screenshot owner ops@example.com token sk-demo-secret"),
        EvidenceFixture("ev-pdf-large", "pdf", 400, "Architecture PDF references checkout and postgres"),
        EvidenceFixture("ev-audio-large", "audio", 180, "Incident bridge audio transcript"),
        EvidenceFixture("ev-video-large", "video", 120, "Incident recording aligned with runtime spike"),
    ]
    if partial:
        base[1] = EvidenceFixture("ev-pdf-large", "pdf", 400, "Architecture PDF", fail_stage="page_render")
        base[3] = EvidenceFixture("ev-video-large", "video", 120, "Incident video", fail_stage="frame_extract")
    return base


def run_checkpoint(root: Path) -> dict:
    policy = load_policy(root)
    clean = [process_fixture(x, tenant_id="tenant", policy=policy) for x in deterministic_fixtures()]
    partial = [process_fixture(x, tenant_id="tenant", policy=policy) for x in deterministic_fixtures(partial=True)]
    clean_fusion = fuse(clean, policy=policy)
    partial_fusion = fuse(partial, policy=policy)
    redaction_ok = all((r.redacted_text is None) or ("@" not in r.redacted_text and "sk-demo-secret" not in r.redacted_text) for r in clean)
    modalities = {r.modality for r in clean}
    passed = (
        modalities == set(policy["required_modalities"])
        and clean_fusion["status"] == "READY"
        and partial_fusion["status"] == "PARTIAL"
        and clean_fusion["traceability"] >= policy["minimum_traceability"]
        and partial_fusion["traceability"] >= policy["minimum_traceability"]
        and redaction_ok
        and partial_fusion["surviving_ratio"] >= policy["minimum_surviving_evidence_ratio"]
    )
    return {
        "passed": passed,
        "clean": clean_fusion,
        "partial": partial_fusion,
        "redaction_correctness": 1.0 if redaction_ok else 0.0,
        "clean_results": [asdict(r) for r in clean],
        "partial_results": [asdict(r) for r in partial],
    }
