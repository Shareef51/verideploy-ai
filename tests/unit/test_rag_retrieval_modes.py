from __future__ import annotations

from uuid import uuid4

import pytest

from verideploy.rag.embeddings.schemas import EmbeddingBatchResult, EmbeddingRecord
from verideploy.rag.retrieval.repository import DenseRow, KeywordRow, RetrievalRepository
from verideploy.rag.retrieval.schemas import RetrievalChannel, RetrievalDocumentKind, RetrievalQuery
from verideploy.rag.retrieval.service import HybridRetriever


class Repo(RetrievalRepository):
    def __init__(self):
        self.keyword_calls = 0; self.dense_calls = 0; self.model_id = uuid4(); self.chunk = uuid4(); self.doc = uuid4()
    def keyword_search(self, **kwargs):
        self.keyword_calls += 1
        assert kwargs["document_kinds"] == [RetrievalDocumentKind.RUNBOOK]
        return [KeywordRow(self.chunk, self.doc, "runbook", "Recovery", "restart safely", 0.9, RetrievalDocumentKind.RUNBOOK)]
    def dense_search(self, **kwargs):
        self.dense_calls += 1
        assert kwargs["document_kinds"] == [RetrievalDocumentKind.RUNBOOK]
        return [DenseRow(self.chunk, self.doc, "runbook", "Recovery", "restart safely", 0.05, RetrievalDocumentKind.RUNBOOK)]
    def get_embedding_model_id(self, **kwargs): return self.model_id


class Pipeline:
    def __init__(self): self.calls = 0
    async def embed(self, request):
        self.calls += 1
        return EmbeddingBatchResult(request_id=request.request_id, tenant_id=request.tenant_id, model="m", dimensions=3, records=[EmbeddingRecord(tenant_id=request.tenant_id, content_hash="0"*64, model="m", dimensions=3, registry_version=1, values=[.1,.2,.3])], cache_hits=0, provider_input_count=1)


def query():
    return RetrievalQuery(tenant_id=uuid4(), text="safe restart", top_k=5, candidate_k=10, model_name="m", dimensions=3, document_kinds=[RetrievalDocumentKind.RUNBOOK])


@pytest.mark.asyncio
async def test_keyword_mode_does_not_call_embedding_or_dense_channel():
    repo=Repo(); pipeline=Pipeline(); result=await HybridRetriever(repo,pipeline).retrieve_mode(query(), mode=RetrievalChannel.KEYWORD)
    assert repo.keyword_calls == 1 and repo.dense_calls == 0 and pipeline.calls == 0
    assert result.hits[0].document_kind is RetrievalDocumentKind.RUNBOOK
    assert [c.channel for c in result.hits[0].contributions] == [RetrievalChannel.KEYWORD]


@pytest.mark.asyncio
async def test_dense_mode_does_not_call_keyword_channel():
    repo=Repo(); pipeline=Pipeline(); result=await HybridRetriever(repo,pipeline).retrieve_mode(query(), mode=RetrievalChannel.DENSE)
    assert repo.keyword_calls == 0 and repo.dense_calls == 1 and pipeline.calls == 1
    assert [c.channel for c in result.hits[0].contributions] == [RetrievalChannel.DENSE]
