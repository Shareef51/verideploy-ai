from __future__ import annotations
import os
from uuid import UUID, uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from verideploy.database.session import DatabaseManager
from verideploy.rag.orchestration.repository import PostgresRetrievalPipelineTraceRepository
from verideploy.rag.orchestration.schemas import (
    DecisionAction, PipelineStage, QueryAnalysis, RankingDecision, RetrievalPipelineTrace
)

URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not URL, reason="TEST_POSTGRES_URL is not configured")
TENANT=UUID("11111111-1111-4111-8111-111111111111")
OTHER=UUID("22222222-2222-4222-8222-222222222222")


def test_postgres_trace_is_persisted_tenant_scoped_and_append_only():
    cfg=Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url",URL); command.upgrade(cfg,"head")
    db=DatabaseManager(URL)
    try:
        with db.engine.begin() as conn:
            for tenant,slug in ((TENANT,"postgres-retrieval-pipeline"),(OTHER,"other")):
                conn.execute(text("INSERT INTO tenants (tenant_id,slug,display_name) VALUES (:id,:slug,:name) ON CONFLICT (tenant_id) DO NOTHING"),{"id":str(tenant),"slug":f"{slug}-{str(tenant)[:8]}","name":slug})
        run=uuid4(); chunk=uuid4(); doc=uuid4()
        trace=RetrievalPipelineTrace(
            run_id=run, tenant_id=TENANT, pipeline_version="1.0.0", input_sha256="a"*64,
            analysis=QueryAnalysis(normalized_query="checkout latency",tokens=["checkout","latency"],expansions=[],query_version="deterministic-v1"),
            retrieval_trace_ids=[],
            decisions=[RankingDecision(stage=PipelineStage.RERANK,ordinal=1,chunk_id=chunk,document_id=doc,source_key="runbook://checkout",input_score=.02,output_score=.8,action=DecisionAction.SCORE,reason_code="transparent_weighted_rerank",components={"retrieval_norm":1.0},source_version="b"*64)],
            selected_chunk_ids=[chunk], context_sha256="c"*64,
        )
        repo=PostgresRetrievalPipelineTraceRepository(db); repo.save(trace)
        assert repo.get(tenant_id=TENANT,run_id=run)==trace
        assert repo.get(tenant_id=OTHER,run_id=run) is None
        with pytest.raises(DBAPIError):
            with db.session(tenant_id=TENANT) as session:
                session.execute(text("UPDATE retrieval_pipeline_runs SET query_text='tampered' WHERE run_id=:run"),{"run":str(run)})
    finally:
        db.dispose()
