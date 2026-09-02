# AI-Engineering Job-Description Mapping

> Every skill below is evidence-backed. A claim must link to implementation code and to a test, trace, or measured report.

| Skill | Evidence status | Code | Verification |
|---|---|---|---|
| Python AI/backend engineering | `implemented_and_measured` | `src/verideploy/graphs/runtime.py` | `tests/orchestration/test_agentic_orchestration_checkpoint.py` |
| TypeScript full-stack engineering | `implemented_and_verified` | `apps/gateway/src/main.ts` | `tests/architecture/test_final_production_technology_architecture.py` |
| OpenAI model and embedding integration | `implemented_with_offline_test_doubles` | `src/verideploy/rag/embeddings/openai_provider.py` | `tests/unit/test_rag_retrieval_modes.py` |
| Production RAG and retrieval engineering | `implemented_and_measured` | `src/verideploy/rag/orchestration/service.py` | `tests/rag/test_rag_integration_performance.py` |
| Agentic AI / specialist agents | `implemented_and_measured` | `src/verideploy/agents/supervisor.py` | `tests/orchestration/test_agentic_orchestration_checkpoint.py` |
| LangGraph orchestration and durability | `implemented_runtime_optional_locally` | `src/verideploy/graphs/runtime.py` | `tests/unit/test_langgraph_state_reducers.py` |
| MCP governed tool integration | `implemented_and_security_governed` | `src/verideploy/mcp/security.py` | `tests/unit/test_mcp_gateway.py` |
| Multimodal AI evidence processing | `implemented_and_measured` | `src/verideploy/multimodal/checkpoint/integration.py` | `tests/multimodal/test_multimodal_integration_checkpoint.py` |
| Production APIs and typed contracts | `implemented_and_contract_tested` | `apps/gateway/src/main.ts` | `tests/contracts/test_final_response_event_schemas.py` |
| Real-time event-driven systems | `implemented_and_tested` | `src/verideploy/realtime/flow.py` | `tests/realtime/test_complete_realtime_api_flow.py` |
| LLM evaluation and regression gates | `implemented_and_measured` | `src/verideploy/evaluation/runner.py` | `tests/release_candidate/test_release_candidate_checkpoint.py` |
| LLMOps data and observability platform | `implemented_and_operationalized` | `src/verideploy/llmops/service.py` | `tests/unit/test_llmops_data_platform.py` |
| AI/application security and guardrails | `implemented_and_scanned` | `src/verideploy/security/architecture.py` | `tests/security/test_production_security_architecture.py` |
| Cloud-native platform engineering | `implemented_and_deployment_validated` | `infrastructure/helm/verideploy/templates/workloads.yaml` | `tests/platform/test_kubernetes_scalability_resilience.py` |

## Recruiter-ready positioning

- Built a production-grade Agentic AI platform using Python, TypeScript, OpenAI integration, RAG, LangGraph-style durable orchestration, MCP-governed tools, multimodal evidence processing, and event-driven APIs.
- Implemented measurable RAG, agent, safety, multimodal, security, and release-candidate evaluation gates; claims in this document point to the exact code and verification artifacts.
- Designed cloud-native deployment and operational controls with Kubernetes/Helm, Kafka, PostgreSQL/pgvector, Redis, object storage, OIDC, guardrails, auditability, and observability.

## Claiming policy

Do not convert CI-enforced or environment-limited evidence into a claim of local execution. In particular, the LangGraph package runtime remains optional in this execution container; the graph architecture, state/reducer contracts, checkpoint behavior, and orchestration checkpoint are implemented and tested through the repository’s deterministic runtime boundaries.
