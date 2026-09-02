from __future__ import annotations
import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine,text
from verideploy.database.session import DatabaseManager
from verideploy.rag.visual_retrieval.repository import PostgresVisualPageRepository

URL=os.getenv('TEST_POSTGRES_URL')
pytestmark=pytest.mark.skipif(not URL,reason='TEST_POSTGRES_URL is not configured')

def test_tables_rls_and_tenant_context():
    assert URL
    engine=create_engine(URL,future=True)
    with engine.begin() as c:
        rows=c.execute(text("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('visual_documents','visual_pages','visual_page_indexes') ORDER BY relname")).all()
        assert len(rows)==3 and all(r[1] and r[2] for r in rows)
    db=DatabaseManager(URL); repo=PostgresVisualPageRepository(db)
    # Repository must always install transaction tenant context; smoke via an empty indexed-page lookup.
    tenant=uuid4(); assert repo.list_indexed_pages(tenant_id=tenant,backend=__import__('verideploy.rag.visual_retrieval.schemas',fromlist=['VisualBackend']).VisualBackend.CPU_FALLBACK,model_name='missing')==[]
