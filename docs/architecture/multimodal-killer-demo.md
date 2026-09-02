# Multimodal Killer Demo

Multimodal Killer Demo composes the production ingestion, investigation, evidence, citation, critic, audit, approval, Kafka and live-UI boundaries into a single recruiter-ready synthetic scenario.

## Evidence

The demo fuses seven synthetic sources: pull request, architecture PDF, Grafana screenshot, incident recording, runbook, runtime signals, and historical RCA. Each source has a stable evidence ID and citation ID and is ingested through the existing public NestJS ingestion boundary.

## Decision safety

The synthetic conclusion is that checkout-v2.19.0 most likely introduced database pool contention. The critic must remain visible and a rollback is represented only as a dry-run action. A signed human approval request is created with `release_reviewer` policy; execution remains disabled until approval.

## Explainability

The UI exposes graph stages, evidence/citations, confidence, latency budget, estimated LLM cost, critic result and approval status. No hidden direct database edit or private FastAPI call is used by the browser.
