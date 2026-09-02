from __future__ import annotations

from functools import lru_cache

from verideploy.config import get_settings
from verideploy.database.session import DatabaseManager
from verideploy.database.factory import create_database_manager
from verideploy.topology.repository import PostgresTopologyRepository
from verideploy.topology.service import TopologyService


@lru_cache
def get_topology_service() -> TopologyService:
    settings = get_settings()
    db = create_database_manager(settings)
    return TopologyService(PostgresTopologyRepository(db))
