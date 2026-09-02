import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")


def _alembic_config() -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", str(POSTGRES_URL))
    return cfg


def test_migrate_up_down_and_restore_head() -> None:
    assert POSTGRES_URL is not None
    cfg = _alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(POSTGRES_URL, future=True)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        assert connection.scalar(text("SELECT indexname FROM pg_indexes WHERE indexname='ix_vector_embeddings_hnsw_cosine'"))
        assert connection.scalar(text("SELECT relrowsecurity FROM pg_class WHERE oid='vector_embeddings'::regclass")) is True
        assert connection.scalar(text("SELECT relforcerowsecurity FROM pg_class WHERE oid='vector_embeddings'::regclass")) is True
    command.downgrade(cfg, "base")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.vector_embeddings')")) is None
        assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
    command.upgrade(cfg, "head")


def test_rls_isolates_tenants_and_hnsw_plan_is_available() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, future=True)
    tenant_a, tenant_b = uuid4(), uuid4()
    emb_a, emb_b = uuid4(), uuid4()
    model_id = "00000000-0000-4000-8000-000000000012"
    vector = "[" + ",".join(["0"] * 3072) + "]"
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO tenants (tenant_id, slug, display_name) VALUES (:id, :slug, :name)"), {"id": str(tenant_a), "slug": f"a-{tenant_a}", "name": "Tenant A"})
        connection.execute(text("INSERT INTO tenants (tenant_id, slug, display_name) VALUES (:id, :slug, :name)"), {"id": str(tenant_b), "slug": f"b-{tenant_b}", "name": "Tenant B"})
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_a)})
        connection.execute(text("INSERT INTO vector_embeddings (embedding_id, tenant_id, embedding_model_id, content_hash, dimensions, state, embedding) VALUES (:eid, :tenant, :model, :hash, 3072, 'CURRENT', CAST(:vector AS vector(3072)))"), {"eid": str(emb_a), "tenant": str(tenant_a), "model": model_id, "hash": "a"*64, "vector": vector})
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_b)})
        connection.execute(text("INSERT INTO vector_embeddings (embedding_id, tenant_id, embedding_model_id, content_hash, dimensions, state, embedding) VALUES (:eid, :tenant, :model, :hash, 3072, 'CURRENT', CAST(:vector AS vector(3072)))"), {"eid": str(emb_b), "tenant": str(tenant_b), "model": model_id, "hash": "b"*64, "vector": vector})

    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_a)})
        visible = connection.execute(text("SELECT tenant_id FROM vector_embeddings")).scalars().all()
        assert visible == [tenant_a]
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = connection.execute(text("EXPLAIN SELECT embedding_id FROM vector_embeddings WHERE tenant_id=:tenant ORDER BY embedding <=> CAST(:vector AS vector) LIMIT 5"), {"tenant": str(tenant_a), "vector": vector}).scalars().all()
        assert any("ix_vector_embeddings_hnsw_cosine" in line for line in plan)
