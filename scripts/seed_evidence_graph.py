from __future__ import annotations
from verideploy.config import get_settings
from verideploy.database.session import DatabaseManager
from verideploy.evidence_graph.repository import PostgresEvidenceGraphRepository
from verideploy.evidence_graph.seed import seed_nexuspay_demo_graph
from verideploy.evidence_graph.service import EvidenceGraphService

def main()->None:
    settings=get_settings();db=DatabaseManager(settings.database_url,pool_size=settings.db_pool_size,max_overflow=settings.db_max_overflow,pool_timeout_seconds=settings.db_pool_timeout_seconds)
    try:
        snapshot=seed_nexuspay_demo_graph(EvidenceGraphService(PostgresEvidenceGraphRepository(db)))
        print(f"seeded evidence graph entities={len(snapshot.entities)} edges={len(snapshot.edges)} sha256={snapshot.snapshot_sha256}")
    finally: db.dispose()
if __name__=="__main__":main()
