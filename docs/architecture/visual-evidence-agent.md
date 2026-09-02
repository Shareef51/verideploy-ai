# VisualEvidenceAgent

Visual Evidence Agent composes existing visual capabilities instead of creating a parallel vision stack. The agent performs bounded query planning, Visual Document Retrieval page-level visual search, and Image Intelligence Layer secure image intelligence. Candidate pages are identified by retrieval score, but search score is never treated as visual proof. Each selected page is re-read from the indexed local artifact, SHA-256 verified against the Visual Document Retrieval record, passed through Image Intelligence Layer secure image preparation/provenance, and analyzed with the strict dashboard, architecture, or error-screen schema.

## Runtime flow

`Supervisor/Planner -> VisualEvidenceAgent -> visual search -> indexed page SHA verification -> ImageIntelligenceService -> direct observations + derived findings -> confidence/sufficiency`

The agent is read-only and requires `visual.evidence.read`. Trusted `document_id` scope is authoritative; model output may match or omit it, but cannot broaden it.

## Evidence model

Direct observations preserve normalized evidence locators and confidence. Derived findings are explicitly typed as model inference, dashboard anomaly, architecture component, architecture relationship, or error signal, and each retains the supporting observation IDs. This preserves the Image Intelligence Layer distinction between observation and inference.

## Confidence qualification

Visual evidence is not silently accepted when quality is weak. The result records `high`, `moderate`, `low`, or `insufficient` confidence plus explicit reasons. Current deterministic reasons include `no_visual_evidence`, `visual_analysis_unavailable`, `low_resolution`, `no_direct_observations`, `missing_evidence_locators`, and `low_confidence`.

The short-side resolution threshold, minimum confidence, analysis count, and tool budget are configuration-driven.

## Failure behavior

A missing page or SHA mismatch is rejected before any image model call. Failure of one candidate analysis is contained; remaining candidates can still produce evidence. If no usable visual evidence remains, the agent returns an explicit insufficient result rather than inventing visual content.
