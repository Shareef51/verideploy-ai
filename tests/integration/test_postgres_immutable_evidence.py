from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from verideploy.database.session import DatabaseManager
from verideploy.evidence.repository import EvidenceNotFoundError, PostgresEvidenceRepository
from verideploy.evidence.schemas import ConfidenceInputs, EvidenceCreate, EvidenceKind, EvidenceParent, EvidenceVersionCreate, ParentRelation, Provenance, RetentionClass, RetentionPolicy, SourceLocator
from verideploy.evidence.service import EvidenceService

URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not URL,reason="TEST_POSTGRES_URL is not configured")
TENANT=UUID("10000000-0000-0000-0000-000000000030")
OTHER=UUID("20000000-0000-0000-0000-000000000030")


def _common():
    now=datetime.now(timezone.utc)
    return dict(
        confidence_inputs=ConfidenceInputs(source_confidence=1.0,extraction_confidence=0.9,temporal_confidence=1.0,corroboration_count=1),
        provenance=Provenance(producer="test",method="direct",source_locator=SourceLocator(source_system="test",source_record_id="r1",locator="test://r1",observed_at=now),correlation_id="pg",synthetic=True),
        retention=RetentionPolicy(retention_class=RetentionClass.AUDIT,retain_until=now+timedelta(days=3650)),
    )


def test_postgres_evidence_is_append_only_and_lineage_is_tenant_isolated():
    cfg=Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url",URL); command.upgrade(cfg,"head")
    db=DatabaseManager(URL)
    with db.engine.begin() as conn:
        for tenant,name in ((TENANT,"postgres-immutable-evidence"),(OTHER,"other")):
            conn.execute(text("INSERT INTO tenants (tenant_id,slug,display_name) VALUES (:id,:slug,:name) ON CONFLICT (tenant_id) DO NOTHING"),{"id":str(tenant),"slug":f"{name}-{str(tenant)[:8]}","name":name})
    svc=EvidenceService(PostgresEvidenceRepository(db)); eid=uuid4()
    first=svc.create(EvidenceCreate(tenant_id=TENANT,evidence_id=eid,kind=EvidenceKind.LOG,content={"message":"pool exhausted"},**_common()))
    derived=svc.create(EvidenceCreate(tenant_id=TENANT,evidence_id=uuid4(),kind=EvidenceKind.ANALYSIS,content={"finding":"pool saturation"},parents=(EvidenceParent(parent_record_id=first.record_id,relation=ParentRelation.DERIVED_FROM),),derived=True,**_common()))
    second=svc.create_version(EvidenceVersionCreate(tenant_id=TENANT,evidence_id=eid,previous_record_id=first.record_id,content={"message":"pool exhausted confirmed"},**_common()))
    assert svc.lineage(tenant_id=TENANT,record_id=first.record_id).children
    with pytest.raises(Exception):
        with db.tenant_session(TENANT) as session:
            session.execute(text("UPDATE evidence_versions SET content='{}'::jsonb WHERE record_id=:rid"),{"rid":str(first.record_id)})
            session.commit()
    assert svc.get(tenant_id=TENANT,record_id=first.record_id).content == {"message":"pool exhausted"}
    assert svc.latest(tenant_id=TENANT,evidence_id=eid).record_id == second.record_id
    assert svc.lineage(tenant_id=TENANT,record_id=derived.record_id).parents[0].record_id == first.record_id
    with pytest.raises(EvidenceNotFoundError): svc.get(tenant_id=OTHER,record_id=first.record_id)
    db.dispose()
