from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from verideploy.database.session import DatabaseManager
from verideploy.graphs.saved_state import PostgresSavedStateRepository


TEST_POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not TEST_POSTGRES_URL, reason="TEST_POSTGRES_URL is required for PostgreSQL state tests")


def _sync_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace("postgresql://", "postgresql+psycopg://", 1)


def test_postgres_state_roundtrip_rls_and_append_only(tmp_path):
    from alembic import command
    from alembic.config import Config

    url = _sync_url(TEST_POSTGRES_URL)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    tenant, other, run_id = uuid4(), uuid4(), uuid4()
    engine = create_engine(url)
    with engine.begin() as conn:
        for tenant_id in (tenant, other):
            conn.execute(text("INSERT INTO tenants (tenant_id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"), {"id": tenant_id, "name": f"{tenant_id}"})
        conn.execute(text("""
            INSERT INTO graph_runs
              (run_id, tenant_id, thread_id, graph_name, graph_version, correlation_id, status, last_sequence, created_at, updated_at)
            VALUES (:run, :tenant, :thread, 'live', '1', 'corr', 'RUNNING', 0, now(), now())
        """), {"run": run_id, "tenant": tenant, "thread": str(run_id)})
    engine.dispose()

    manager = DatabaseManager(url)
    repo = PostgresSavedStateRepository(manager)
    snapshot = repo.save_snapshot(
        tenant_id=tenant, run_id=run_id, snapshot_kind="input",
        state={"tenant_id": str(tenant), "run_id": str(run_id), "investigation_id": "active-39", "node_outputs": {"intake": {"ok": True}}},
    )
    assert repo.latest_snapshot(tenant_id=tenant, run_id=run_id).state_sha256 == snapshot.state_sha256
    assert repo.latest_snapshot(tenant_id=other, run_id=run_id) is None

    with manager.tenant_session(tenant) as session:
        with pytest.raises(Exception, match="append-only"):
            session.execute(text("UPDATE graph_state_snapshots SET snapshot_kind='result' WHERE snapshot_id=:id"), {"id": snapshot.snapshot_id})
            session.commit()
        session.rollback()
    manager.dispose()
