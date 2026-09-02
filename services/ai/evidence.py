from __future__ import annotations

from functools import lru_cache

from verideploy.config import get_settings
from verideploy.database.session import DatabaseManager
from verideploy.database.factory import create_database_manager
from verideploy.evidence.repository import PostgresEvidenceRepository
from verideploy.evidence.service import EvidenceService


@lru_cache
def get_evidence_service() -> EvidenceService:
    settings = get_settings()
    db = create_database_manager(settings)
    return EvidenceService(PostgresEvidenceRepository(db))
