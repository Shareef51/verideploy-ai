from uuid import uuid4

from fastapi.testclient import TestClient

from services.ai.main import app
from services.ai.retrieval import get_hybrid_retriever
from verideploy.rag.retrieval.schemas import HybridRetrievalResult, RetrievalTrace


class StubRetriever:
    async def retrieve(self, request):
        return HybridRetrievalResult(
            hits=[],
            trace=RetrievalTrace(
                tenant_id=request.tenant_id, query_text=request.text, keyword_candidates=0, dense_candidates=0,
                rrf_k=60, source_diversity_limit=2, selected_chunk_ids=[], ranking=[]
            ),
        )


def test_retrieval_api_requires_trusted_identity_and_tenant_scope(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    app.dependency_overrides[get_hybrid_retriever] = lambda: StubRetriever()
    tenant = uuid4(); other = uuid4()
    body = {"tenant_id": str(tenant), "text": "pool", "top_k": 5, "candidate_k": 10, "model_name": "m", "dimensions": 3}
    with TestClient(app) as client:
        assert client.post("/internal/v1/retrieval/hybrid", json=body).status_code == 401
        assert client.post("/internal/v1/retrieval/hybrid", json=body, headers={"x-internal-service":"verideploy-gateway", "x-tenant-id":str(other)}).status_code == 403
        response = client.post("/internal/v1/retrieval/hybrid", json=body, headers={"x-internal-service":"verideploy-gateway", "x-tenant-id":str(tenant)})
        assert response.status_code == 200
        assert response.json()["trace"]["tenant_id"] == str(tenant)
    app.dependency_overrides.clear()
