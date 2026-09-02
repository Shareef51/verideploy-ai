from __future__ import annotations
import os
from uuid import UUID, uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from verideploy.database.session import DatabaseManager
from verideploy.rag.orchestration.schemas import ParentResolvedContext, PipelineCandidate, QueryAnalysis, RetrievalPipelineResult, RetrievalPipelineTrace
from verideploy.rag.retrieval.schemas import RetrievalChannel, RetrievalDocumentKind
from verideploy.rag.self_corrective.repository import PostgresSelfCorrectiveRunRepository
from verideploy.rag.self_corrective.schemas import CorrectiveAttempt, EvidenceGrade, EvidenceGradeResult, SelfCorrectiveRAGResult, StopReason

URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not URL,reason="TEST_POSTGRES_URL is not configured")
TENANT=UUID("11111111-1111-4111-8111-111111111111")
OTHER=UUID("22222222-2222-4222-8222-222222222222")


def _result():
    chunk,doc=uuid4(),uuid4()
    pipeline=RetrievalPipelineResult(
        candidates=[PipelineCandidate(chunk_id=chunk,document_id=doc,source_key="runbook://checkout",title="Checkout",content="evidence",document_kind=RetrievalDocumentKind.RUNBOOK,retrieval_score=.02,rerank_score=.8,final_rank=1,contributing_queries=["checkout"],channels=[RetrievalChannel.HYBRID],source_version="a"*64)],
        context=[ParentResolvedContext(chunk_id=chunk,document_id=doc,source_key="runbook://checkout",title="Checkout",content="ctx",content_sha256="b"*64,source_version="a"*64,estimated_tokens=2)],
        trace=RetrievalPipelineTrace(run_id=uuid4(),tenant_id=TENANT,pipeline_version="1.0.0",input_sha256="c"*64,analysis=QueryAnalysis(normalized_query="checkout",tokens=["checkout"],expansions=[],query_version="1.0.0"),retrieval_trace_ids=[],decisions=[],selected_chunk_ids=[chunk],context_sha256="d"*64),
    )
    grade=EvidenceGradeResult(grade=EvidenceGrade.SUFFICIENT,score=.8,candidate_count=1,source_count=1,context_count=1,top_rerank_score=.8,reasons=())
    attempt=CorrectiveAttempt(attempt=1,query="checkout",action="retrieve",retrieval_run_id=pipeline.trace.run_id,grade=grade,effective_scope_fingerprint="e"*64)
    return SelfCorrectiveRAGResult(run_id=uuid4(),tenant_id=TENANT,answerable=True,qualified=False,stop_reason=StopReason.SUFFICIENT_EVIDENCE,attempts=[attempt],final_retrieval=pipeline,controller_version="1.0.0")


def test_postgres_history_is_tenant_scoped_and_append_only():
    assert URL
    cfg=Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url",URL); command.upgrade(cfg,"head")
    db=DatabaseManager(URL)
    try:
        with db.engine.begin() as conn:
            for tenant,slug in ((TENANT,"postgres-self-corrective-rag"),(OTHER,"other")):
                conn.execute(text("INSERT INTO tenants (tenant_id,slug,display_name) VALUES (:id,:slug,:name) ON CONFLICT (tenant_id) DO NOTHING"),{"id":str(tenant),"slug":f"{slug}-{str(tenant)[:8]}","name":slug})
        payload=_result(); repo=PostgresSelfCorrectiveRunRepository(db); repo.save(payload)
        assert repo.get(tenant_id=TENANT,run_id=payload.run_id)==payload
        assert repo.get(tenant_id=OTHER,run_id=payload.run_id) is None
        with pytest.raises(DBAPIError):
            with db.session(tenant_id=TENANT) as session:
                session.execute(text("UPDATE self_corrective_rag_runs SET stop_reason='tampered' WHERE run_id=:run"),{"run":str(payload.run_id)})
    finally:
        db.dispose()
