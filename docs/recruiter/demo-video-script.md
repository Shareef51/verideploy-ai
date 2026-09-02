# Recruiter Demo Video Script

Target length: **8–10 minutes**. All demo data shown should be synthetic.

## 0:00–0:45 — Problem and value
- Introduce VeriDeploy AI as release assurance + incident intelligence, not a generic chatbot.
- Explain the fragmented-evidence problem: code, deployments, dashboards, logs, documents, video, runbooks, and historical RCAs.

## 0:45–2:00 — Architecture
- Show `docs/architecture/topology.mmd`.
- Trace Browser → Next.js → NestJS → Kafka → Python/LangGraph/OpenAI/MCP → data stores → observability.
- Call out the public/private API boundary and tenant/security controls.

## 2:00–4:30 — Multimodal killer demo
- Open `/demos/multimodal-killer`.
- Show PR, architecture PDF, Grafana screenshot, incident video, runbook, runtime signals, and historical RCA.
- Explain evidence IDs, citations, critic stage, latency/cost fields, and the human review gate.
- State clearly that the recruiter flow is synthetic and rollback remains dry-run until approval.

## 4:30–6:00 — RAG + agent orchestration
- Explain hybrid retrieval, reranking, metadata/tenant filters, citation validation, and the clean-index checkpoint.
- Explain supervisor/planner/specialist agents, fan-out/fan-in, bounded retry, critic correction, durable checkpointing, and restart recovery.

## 6:00–7:15 — Production engineering
- Show Kafka idempotency/order/DLQ controls, audit trail, guardrails, MCP governance, Kubernetes/Helm, readiness, and observability.
- Explain why NestJS is the public boundary while Python remains private.

## 7:15–8:30 — Evaluation and measured evidence
- Show the release-candidate and resume/interview-evidence reports.
- Distinguish measured results from environment-limited or synthetic-demo values.
- Mention that browser execution is CI-enforced when local dependencies are unavailable; do not claim unexecuted tests.

## 8:30–9:30 — Limitations and next production validation
- State the clean-room production validation still required: real cloud environment, real managed dependencies, signed release artifacts, live browser suite, and operational drills.
- Close with the safe-action principle: evidence first, critic second, human approval before consequential changes.
