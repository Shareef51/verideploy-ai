from __future__ import annotations
from functools import lru_cache
from verideploy.config import get_settings
from verideploy.database.session import DatabaseManager
from verideploy.database.factory import create_database_manager
from verideploy.evidence.repository import PostgresEvidenceRepository
from verideploy.evidence_graph.repository import PostgresEvidenceGraphRepository
from verideploy.evidence_graph.service import EvidenceGraphService

@lru_cache
def get_evidence_graph_service() -> EvidenceGraphService:
    settings=get_settings()
    db=create_database_manager(settings)
    return EvidenceGraphService(PostgresEvidenceGraphRepository(db),PostgresEvidenceRepository(db))
