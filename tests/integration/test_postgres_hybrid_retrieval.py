import os
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from verideploy.database.session import DatabaseManager
from verideploy.rag.retrieval.repository import PostgresHybridRetrievalRepository

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")


def _alembic_config() -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", str(POSTGRES_URL))
    return cfg


def _vector(first: float) -> str:
    values = ["0"] * 3072
    values[0] = str(first)
    return "[" + ",".join(values) + "]"


def test_postgres_keyword_dense_and_tenant_isolation() -> None:
    assert POSTGRES_URL is not None
    command.upgrade(_alembic_config(), "head")
    engine = create_engine(POSTGRES_URL, future=True)
    tenant_a, tenant_b = uuid4(), uuid4()
    doc_a, doc_b = uuid4(), uuid4()
    chunk_a, chunk_b = uuid4(), uuid4()
    emb_a, emb_b = uuid4(), uuid4()
    model_id = "00000000-0000-4000-8000-000000000012"

    with engine.begin() as connection:
        for tenant, slug in ((tenant_a, "a"), (tenant_b, "b")):
            connection.execute(
                text("INSERT INTO tenants (tenant_id, slug, display_name) VALUES (:id,:slug,:name) ON CONFLICT DO NOTHING"),
                {"id": str(tenant), "slug": f"{slug}-{tenant}", "name": slug},
            )
        for tenant, doc, chunk, emb, source, content, vector in (
            (tenant_a, doc_a, chunk_a, emb_a, "runbook-a", "checkout database connection pool exhausted", _vector(1.0)),
            (tenant_b, doc_b, chunk_b, emb_b, "runbook-b", "checkout database connection pool exhausted", _vector(1.0)),
        ):
            connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)})
            connection.execute(
                text("INSERT INTO retrieval_documents (document_id,tenant_id,source_key,title) VALUES (:doc,:tenant,:source,:title)"),
                {"doc": str(doc), "tenant": str(tenant), "source": source, "title": "DB pool"},
            )
            connection.execute(
                text("INSERT INTO retrieval_chunks (chunk_id,tenant_id,document_id,ordinal,content,content_hash) VALUES (:chunk,:tenant,:doc,0,:content,:hash)"),
                {"chunk": str(chunk), "tenant": str(tenant), "doc": str(doc), "content": content, "hash": ("a" if tenant == tenant_a else "b") * 64},
            )
            connection.execute(
                text("INSERT INTO vector_embeddings (embedding_id,tenant_id,embedding_model_id,document_id,chunk_id,content_hash,dimensions,state,embedding) VALUES (:emb,:tenant,:model,:doc,:chunk,:hash,3072,'CURRENT',CAST(:vector AS vector(3072)))"),
                {"emb": str(emb), "tenant": str(tenant), "model": model_id, "doc": str(doc), "chunk": str(chunk), "hash": ("c" if tenant == tenant_a else "d") * 64, "vector": vector},
            )

    repo = PostgresHybridRetrievalRepository(DatabaseManager(POSTGRES_URL))
    keyword = repo.keyword_search(tenant_id=tenant_a, query="database pool exhausted", limit=5)
    assert [row.chunk_id for row in keyword] == [chunk_a]
    dense = repo.dense_search(
        tenant_id=tenant_a,
        embedding_model_id=UUID(model_id),
        query_vector=[1.0] + [0.0] * 3071,
        limit=5,
    )
    assert [row.chunk_id for row in dense] == [chunk_a]

    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_a)})
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        fts_plan = connection.execute(
            text("EXPLAIN SELECT chunk_id FROM retrieval_chunks WHERE tenant_id=:tenant AND search_vector @@ websearch_to_tsquery('english','database pool')"),
            {"tenant": str(tenant_a)},
        ).scalars().all()
        assert any("ix_retrieval_chunks_search_gin" in line for line in fts_plan)
