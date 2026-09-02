from uuid import uuid4

from fastapi.testclient import TestClient

from services.ai.agents import get_rag_agent
from services.ai.main import app
from verideploy.agents.rag import EvidenceSufficiency, RAGAgentResult, RAGQueryAnalysis
from verideploy.rag.retrieval.schemas import RetrievalChannel, RetrievalDocumentKind


class RAGStub:
    async def run(self, request, *, authorization, budget, model_name, dimensions, candidate_k, min_evidence, min_sources):
        return RAGAgentResult(
            analysis=RAGQueryAnalysis(
                normalized_query="checkout runbook",
                intent="runbook",
                retrieval_mode="keyword",
                document_kinds=["runbook"],
                service="checkout",
                environment="production",
                query_expansions=[],
                top_k=5,
                rationale="exact runbook identifiers",
            ),
            evidence=[],
            sufficiency=EvidenceSufficiency(
                sufficient=False,
                evidence_count=0,
                unique_sources=0,
                covered_document_kinds=[],
                required_document_kinds=[RetrievalDocumentKind.RUNBOOK],
                reason_codes=["insufficient_evidence_count", "insufficient_source_diversity", "required_document_kind_missing"],
            ),
            retrieval_traces=[],
            tool_calls_used=1,
        )


def payload(tenant):
    return {
        "request": {
            "tenant_id": str(tenant),
            "user_id": "u1",
            "correlation_id": "corr-20",
            "objective": "find checkout runbook",
            "context": {"service": "checkout", "environment": "production"},
        },
        "permissions": ["rag.retrieval.read"],
    }


def test_private_rag_endpoint_enforces_trusted_service_and_tenant_scope():
    tenant = uuid4(); app.dependency_overrides[get_rag_agent] = lambda: RAGStub()
    try:
        client = TestClient(app)
        assert client.post('/internal/v1/agents/rag', json=payload(tenant), headers={'x-tenant-id':str(tenant),'x-user-id':'u1'}).status_code == 401
        assert client.post('/internal/v1/agents/rag', json=payload(tenant), headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(uuid4()),'x-user-id':'u1'}).status_code == 403
        ok = client.post('/internal/v1/agents/rag', json=payload(tenant), headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(tenant),'x-user-id':'u1'})
        assert ok.status_code == 200
        assert ok.json()['analysis']['retrieval_mode'] == RetrievalChannel.KEYWORD.value
        assert ok.json()['sufficiency']['sufficient'] is False
    finally:
        app.dependency_overrides.clear()
