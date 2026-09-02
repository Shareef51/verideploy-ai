import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from verideploy.database.session import DatabaseManager
from verideploy.rag.retrieval.repository import PostgresHybridRetrievalRepository
from verideploy.rag.retrieval.schemas import RetrievalDocumentKind

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")


def test_postgres_document_kind_filter_is_tenant_scoped() -> None:
    assert POSTGRES_URL is not None
    cfg = Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url", POSTGRES_URL); command.upgrade(cfg, "head")
    engine = create_engine(POSTGRES_URL, future=True)
    tenant = uuid4(); runbook_doc = uuid4(); architecture_doc = uuid4(); runbook_chunk = uuid4(); architecture_chunk = uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO tenants (tenant_id,slug,display_name) VALUES (:id,:slug,'postgres-rag-metadata') ON CONFLICT DO NOTHING"), {"id":str(tenant),"slug":f"{tenant}"})
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant":str(tenant)})
        for doc, chunk, source, kind, content, hash_char in (
            (runbook_doc, runbook_chunk, "db-runbook", "runbook", "checkout database pool recovery restart", "a"),
            (architecture_doc, architecture_chunk, "db-architecture", "architecture", "checkout database pool topology diagram", "b"),
        ):
            connection.execute(text("INSERT INTO retrieval_documents (document_id,tenant_id,source_key,title,document_kind) VALUES (:doc,:tenant,:source,:title,:kind)"), {"doc":str(doc),"tenant":str(tenant),"source":source,"title":source,"kind":kind})
            connection.execute(text("INSERT INTO retrieval_chunks (chunk_id,tenant_id,document_id,ordinal,content,content_hash) VALUES (:chunk,:tenant,:doc,0,:content,:hash)"), {"chunk":str(chunk),"tenant":str(tenant),"doc":str(doc),"content":content,"hash":hash_char*64})
    repo = PostgresHybridRetrievalRepository(DatabaseManager(POSTGRES_URL))
    rows = repo.keyword_search(tenant_id=tenant, query="checkout database pool", limit=10, document_kinds=[RetrievalDocumentKind.RUNBOOK])
    assert [row.chunk_id for row in rows] == [runbook_chunk]
    assert rows[0].document_kind is RetrievalDocumentKind.RUNBOOK
