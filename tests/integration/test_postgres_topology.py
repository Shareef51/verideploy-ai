import os
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config

from verideploy.database.session import DatabaseManager
from verideploy.topology.repository import PostgresTopologyRepository
from verideploy.topology.seed import TENANT_ID, build_nexuspay_topology
from verideploy.topology.service import TopologyService

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")


def test_postgres_topology_persists_idempotently_and_is_tenant_scoped() -> None:
    assert POSTGRES_URL is not None
    cfg = Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url", POSTGRES_URL); command.upgrade(cfg, "head")
    db = DatabaseManager(POSTGRES_URL)
    try:
        service = TopologyService(PostgresTopologyRepository(db))
        snapshot = build_nexuspay_topology()
        service.seed(snapshot); service.seed(snapshot)
        loaded = service.get(tenant_id=TENANT_ID)
        assert loaded == snapshot
        assert service.get(tenant_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")) is None
    finally:
        db.dispose()
