from __future__ import annotations
import os
from uuid import UUID
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from verideploy.database.session import DatabaseManager
from verideploy.evidence_graph.repository import PostgresEvidenceGraphRepository
from verideploy.evidence_graph.schemas import GraphEntityType
from verideploy.evidence_graph.seed import seed_nexuspay_demo_graph
from verideploy.evidence_graph.service import EvidenceGraphService

URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not URL,reason="TEST_POSTGRES_URL is not configured")
TENANT=UUID("11111111-1111-4111-8111-111111111111")
OTHER=UUID("22222222-2222-4222-8222-222222222222")

def test_postgres_graph_path_is_queryable_and_tenant_isolated():
    cfg=Config("alembic.ini");cfg.set_main_option("sqlalchemy.url",URL);command.upgrade(cfg,"head")
    db=DatabaseManager(URL)
    try:
        with db.engine.begin() as conn:
            for t,n in ((TENANT,"postgres-evidence-graph"),(OTHER,"other")):
                conn.execute(text("INSERT INTO tenants (tenant_id,slug,display_name) VALUES (:id,:slug,:name) ON CONFLICT (tenant_id) DO NOTHING"),{"id":str(t),"slug":f"{n}-{str(t)[:8]}","name":n})
        svc=EvidenceGraphService(PostgresEvidenceGraphRepository(db)); snap=seed_nexuspay_demo_graph(svc); by_type={e.entity_type:e for e in snap.entities}
        path=svc.path(tenant_id=TENANT,source_entity_id=by_type[GraphEntityType.PULL_REQUEST].entity_id,target_entity_id=by_type[GraphEntityType.ROOT_CAUSE].entity_id,max_depth=4)
        assert [e.entity_type.value for e in path.entities]==["pull_request","service","incident","root_cause"]
        assert svc.repository.list_entities(tenant_id=OTHER)==()
    finally: db.dispose()
