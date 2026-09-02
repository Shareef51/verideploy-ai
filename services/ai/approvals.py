from __future__ import annotations

from functools import lru_cache

from verideploy.approvals.repository import PostgresApprovalRepository
from verideploy.approvals.service import HumanApprovalService
from verideploy.approvals.signing import ApprovalAuditSigner
from verideploy.config import get_settings
from verideploy.database.factory import create_database_manager


@lru_cache
def get_approval_service() -> HumanApprovalService:
    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        raise RuntimeError("approval runtime requires PostgreSQL")
    db = create_database_manager(settings)
    secret = settings.approval_signing_secret or settings.app_secret_key
    return HumanApprovalService(
        repository=PostgresApprovalRepository(db, statement_timeout_ms=settings.db_statement_timeout_ms),
        signer=ApprovalAuditSigner(secret.get_secret_value()),
    )
