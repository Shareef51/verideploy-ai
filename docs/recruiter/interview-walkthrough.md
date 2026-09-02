# 15-Minute Senior-Engineer Interview Walkthrough

## Minute 0–2 — Product and scope
Explain the user problem and why the system is evidence-driven rather than chat-driven. Point to release risk, incident RCA, multimodal evidence, citations, and approval.

## Minute 2–4 — Boundary design
Use the Final Production Technology Architecture topology. Explain browser → Next.js → NestJS public API → Kafka/private Python. Discuss why identity/tenant/tool policy belongs at controlled boundaries.

## Minute 4–7 — RAG and agent runtime
Walk through ingestion, chunking, embeddings, hybrid retrieval, reranking, metadata filters, citation validation, supervisor/planner/specialists, fan-out/fan-in, critic correction, checkpoint/restart, and bounded retries.

## Minute 7–9 — Multimodal and evidence integrity
Explain image/PDF/audio/video processing, redaction-before-persistence, evidence lineage, bounded work units, timeline construction, and explicit PARTIAL outcomes.

## Minute 9–11 — Real-time and operations
Explain Kafka envelopes, ordering keys, transactional outbox/inbox, idempotency, retry/DLQ/replay, WebSocket reconciliation, readiness, Kubernetes scaling, SLOs, alerts, audit, and backup/restore controls.

## Minute 11–13 — Evaluation
Show Evaluation Release Candidate Checkpoint and the clean RAG Integration Performance Checkpoint–79 checkpoints. Explain why measured values are tied to reports and why environment limitations are surfaced explicitly.

## Minute 13–15 — Trade-offs and lessons
Use `docs/career/resume-impact-and-interview-evidence.md`: NestJS/Python boundary, approval over autonomy, bounded multimodal processing, demo identity removal, architecture drift, and CI-vs-local execution truthfulness.

## Deep-dive prompts to be ready for
- Show where tenant isolation is enforced in retrieval and tools.
- Explain the exact failure mode when Kafka delivers duplicates/out of order.
- Explain how the critic decides whether to request more evidence.
- Show how a human approval decision is authenticated and audited.
- Explain what you would measure differently in a live production cloud environment.
