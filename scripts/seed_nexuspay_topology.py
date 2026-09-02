from verideploy.config import get_settings
from verideploy.database.session import DatabaseManager
from verideploy.topology.repository import PostgresTopologyRepository
from verideploy.topology.seed import build_nexuspay_topology
from verideploy.topology.service import TopologyService

settings=get_settings()
if not settings.database_url.startswith("postgresql"):
    raise SystemExit("topology persistence requires PostgreSQL")
db=DatabaseManager(settings.database_url,pool_size=settings.db_pool_size,max_overflow=settings.db_max_overflow,pool_timeout_seconds=settings.db_pool_timeout_seconds)
try:
    snapshot=TopologyService(PostgresTopologyRepository(db)).seed(build_nexuspay_topology())
    print(f"seeded {snapshot.company.name} topology {snapshot.seed_version} {snapshot.seed_sha256}")
finally:
    db.dispose()
