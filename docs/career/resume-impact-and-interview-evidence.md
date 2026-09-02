# VeriDeploy AI — Resume Impact and Interview Evidence

All numeric claims below are rendered from measured repository evidence. Qualifiers are preserved for synthetic, estimated, CI-only, or in-process measurements.

## Resume-ready bullets

- Built VeriDeploy AI as an evidence-driven release assurance and incident intelligence platform with 15 validated production architecture nodes and 19 validated data-flow edges across Next.js, NestJS, Kafka, Python AI services, persistence, security, and observability.
- Engineered hybrid RAG with keyword, dense, visual, reranking, metadata filters, citations, and caching; the deterministic clean-index checkpoint achieved 100% Hybrid Recall@5, 1.00 Hybrid MRR, and an 87.5% warmed-cache hit ratio.
- Implemented supervisor/planner/specialist-agent orchestration with fan-out/fan-in, retries, critic correction, durable recovery, and human approval; 3 deterministic scenarios achieved an aggregate path score of 1.00.
- Established release-candidate quality gates with 700 passing regression tests, 87.32% Python coverage, 4/4 critical mutation probes killed, and 0 critical security findings in the aggregated release-candidate evidence.
- Hardened multimodal evidence processing and production operations with 100% clean-path traceability, 10 readiness domains reviewed, and 0 critical operational gaps in the production-operations review.
- Mapped 14 AI-engineering skill claims to code plus verification evidence, including Python, TypeScript, OpenAI, RAG, LangGraph, MCP, multimodal AI, real-time systems, evaluation, LLMOps, security, and cloud-native engineering.

## STAR stories

### Fail-closed release-candidate evidence
- **Situation:** The release-candidate checkpoint needed to distinguish locally executed evidence from browser tests that could only run in CI in the build environment.
- **Task:** Prevent a recruiter-facing or release-facing report from presenting an unexecuted browser test as a factual pass.
- **Action:** Implemented an explicit RC_READY_FOR_CI state and retained the browser gate as mandatory CI enforcement instead of fabricating local Playwright execution.
- **Result:** The local release-candidate evidence still recorded 700 passing regression tests and 87.32% Python coverage while preserving the browser execution limitation explicitly.

### Removed demo identity from production approval path
- **Situation:** Architecture-integrity review found an earlier demo-era reviewer fallback inside the production approval boundary.
- **Task:** Ensure consequential approval reads and decisions use authenticated production identity and role context.
- **Action:** Removed demo reviewer fallbacks and required gateway user/role context, while retaining dry-run and human-approval safety controls.
- **Result:** The architecture-integrity report completed with no recorded findings after the production boundary was hardened.

### Designed bounded multimodal degradation
- **Situation:** Large multimodal investigations must remain traceable when an extractor fails instead of silently dropping evidence or exhausting resources.
- **Task:** Keep image, PDF, audio, and video processing bounded while preserving evidence lineage through partial failures.
- **Action:** Added hard work-unit limits, redaction-before-persistence, stable trace IDs, explicit DEGRADED evidence states, and a minimum surviving-evidence threshold.
- **Result:** The clean checkpoint retained 100% traceability and the partial-failure fixture preserved degraded evidence lineage rather than hiding failed modalities.

### Converted architecture documentation into an executable contract
- **Situation:** A large multi-service portfolio can drift when diagrams, release metadata, Helm images, and actual service boundaries are maintained independently.
- **Task:** Make the documented architecture verifiably match deployed topology and data flows.
- **Action:** Created one machine-readable topology model and generated/validated diagrams, workload versions, Compose services, security boundaries, and runtime paths from it.
- **Result:** The final topology validates 15 nodes and 19 data-flow edges with no findings in the production architecture report.

## Trade-offs

### Keep NestJS as the sole public application API while Python AI services remain private.
This adds an internal service boundary and contract maintenance cost, but isolates AI execution, centralizes authentication/tenant policy, and keeps browser clients away from private model/tool endpoints.

### Require dry-run plus human approval for consequential remediation rather than autonomous writes.
This sacrifices maximum automation speed for auditability, blast-radius control, and safer production operation.

### Bound multimodal work units and allow explicit PARTIAL results when enough evidence survives.
This may omit expensive evidence beyond configured limits, but prevents unbounded work and preserves degraded-source traceability.

## Cost and latency decisions

- Use the clean-index checkpoint to catch algorithmic retrieval regressions early; its cold p95 was 0.02019 ms, explicitly treated as an in-process benchmark rather than production network latency.
- The synthetic multimodal recruiter flow carries a configured latency budget of 2500 ms and an estimated LLM cost of $0.084; both are labelled budget/estimate values rather than measured production performance or billing.

## Failure lessons

- Do not equate CI wiring with local execution. Record environment limitations explicitly and fail closed on missing evidence.
- Demo conveniences must not survive inside production authorization paths; periodic scope-control reviews should scan production entrypoints for mock identities and bypasses.
- Versioned deployment artifacts can drift independently; compare release metadata, Helm image tags, canary tags, diagrams, and runtime topology in one executable architecture gate.

## Likely recruiter / interviewer questions

- What real problem does VeriDeploy AI solve beyond being an LLM wrapper?
- How does your RAG pipeline prevent unsupported claims and preserve citations?
- Why did you use NestJS plus Python instead of exposing the Python AI service directly?
- How does LangGraph checkpointing and restart recovery work in your design?
- How are MCP tool calls governed and audited?
- What happens when PDF or video extraction fails during an incident investigation?
- Which numbers on your resume are actually measured, and what environment produced them?
- How do you keep consequential AI actions from executing autonomously?
- How do Kafka ordering, retries, idempotency, and DLQ handling work?
- What would you need to validate before calling the system production-ready in a real company environment?
