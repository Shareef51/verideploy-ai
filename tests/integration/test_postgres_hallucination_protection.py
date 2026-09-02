from __future__ import annotations
import os
from uuid import UUID, uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from verideploy.database.session import DatabaseManager
from verideploy.rag.hallucination.repository import PostgresHallucinationProtectionRepository
from verideploy.rag.hallucination.schemas import ClaimReleaseAction, ClaimSupportLabel, HallucinationProtectionResult, VerifiedClaim
from verideploy.rag.self_corrective.schemas import StopReason

URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not URL,reason="TEST_POSTGRES_URL is not configured")
TENANT=UUID("11111111-1111-4111-8111-111111111111")
OTHER=UUID("22222222-2222-4222-8222-222222222222")


def test_postgres_history_is_tenant_scoped_and_append_only():
    assert URL
    cfg=Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url",URL); command.upgrade(cfg,"head")
    db=DatabaseManager(URL)
    source_run=uuid4(); verification=uuid4()
    try:
        with db.engine.begin() as conn:
            for tenant,slug in ((TENANT,"postgres-hallucination-protection"),(OTHER,"other")):
                conn.execute(text("INSERT INTO tenants (tenant_id,slug,display_name) VALUES (:id,:slug,:name) ON CONFLICT (tenant_id) DO NOTHING"),{"id":str(tenant),"slug":f"{slug}-{str(tenant)[:8]}","name":slug})
        # Create the required  parent under tenant scope using a minimal JSON payload; FK/tenant guard is the subject here.
        with db.session(tenant_id=TENANT) as session:
            session.execute(text("""INSERT INTO self_corrective_rag_runs
                (run_id,tenant_id,controller_version,stop_reason,answerable,qualified,result_json)
                VALUES (:run,:tenant,'1.0.0','sufficient_evidence',true,false,CAST(:payload AS jsonb))"""),
                {"run":str(source_run),"tenant":str(TENANT),"payload":'{"stub":true}'})
        claim=VerifiedClaim(claim_id="c1",original_text="supported",released_text="supported",label=ClaimSupportLabel.SUPPORTED,action=ClaimReleaseAction.KEEP,material=True,proposed_confidence=.8,adjusted_confidence=.8)
        result=HallucinationProtectionResult(verification_id=verification,tenant_id=TENANT,self_corrective_run_id=source_run,verifier_version="1.0.0",protected=True,protected_answer="supported",claims=[claim],supported_count=1,uncertain_count=0,unsupported_count=0,unsupported_material_rate=0,prompt_injection_evidence_count=0)
        repo=PostgresHallucinationProtectionRepository(db); repo.save(result)
        assert repo.get(tenant_id=TENANT,verification_id=verification)==result
        assert repo.get(tenant_id=OTHER,verification_id=verification) is None
        with pytest.raises(DBAPIError):
            with db.session(tenant_id=TENANT) as session:
                session.execute(text("UPDATE hallucination_protection_runs SET protected=false WHERE verification_id=:id"),{"id":str(verification)})
    finally:
        db.dispose()
