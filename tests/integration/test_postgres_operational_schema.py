from __future__ import annotations
import os
from uuid import UUID, uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from verideploy.database.session import DatabaseManager

URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not URL,reason="TEST_POSTGRES_URL is not configured")
TENANT=UUID("11111111-1111-4111-8111-111111111111")
OTHER=UUID("22222222-2222-4222-8222-222222222222")


def test_postgres_constraints_lifecycle_idempotency_and_tenant_links():
    cfg=Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url",URL); command.upgrade(cfg,"head")
    db=DatabaseManager(URL)
    try:
        with db.engine.begin() as conn:
            for t,n in ((TENANT,"postgres-operational-schema"),(OTHER,"other")):
                conn.execute(text("INSERT INTO tenants (tenant_id,slug,display_name) VALUES (:id,:slug,:name) ON CONFLICT (tenant_id) DO NOTHING"),{"id":str(t),"slug":f"{n}-{str(t)[:8]}","name":n})
        incident=uuid4(); investigation=uuid4(); outbox1=uuid4(); outbox2=uuid4(); audit=uuid4()
        with db.session(tenant_id=TENANT) as session:
            session.execute(text("INSERT INTO incidents (incident_id,tenant_id,external_key,service_id,severity,status,started_at,payload) VALUES (:id,:tenant,'INC-32',:svc,'SEV1','open',now(),'{}'::jsonb)"),{"id":str(incident),"tenant":str(TENANT),"svc":str(uuid4())})
            session.execute(text("INSERT INTO investigations (investigation_id,tenant_id,incident_id,status,payload) VALUES (:id,:tenant,:incident,'created','{}'::jsonb)"),{"id":str(investigation),"tenant":str(TENANT),"incident":str(incident)})
            session.execute(text("UPDATE investigations SET status='collecting' WHERE investigation_id=:id"),{"id":str(investigation)})
            session.execute(text("INSERT INTO outbox (outbox_id,tenant_id,topic,message_key,idempotency_key,payload) VALUES (:id,:tenant,'incident.events','INC-32','idem-32','{}'::jsonb)"),{"id":str(outbox1),"tenant":str(TENANT)})
            session.execute(text("INSERT INTO audit_events (audit_id,tenant_id,actor_type,actor_id,action,resource_type,resource_id,correlation_id,event_sha256,payload) VALUES (:id,:tenant,'service','test','created','investigation',:rid,'corr-32',:sha,'{}'::jsonb)"),{"id":str(audit),"tenant":str(TENANT),"rid":str(investigation),"sha":"a"*64})
        with pytest.raises(DBAPIError):
            with db.session(tenant_id=TENANT) as session:
                session.execute(text("UPDATE investigations SET status='completed' WHERE investigation_id=:id"),{"id":str(investigation)})
        with pytest.raises(IntegrityError):
            with db.session(tenant_id=TENANT) as session:
                session.execute(text("INSERT INTO outbox (outbox_id,tenant_id,topic,message_key,idempotency_key,payload) VALUES (:id,:tenant,'incident.events','INC-32','idem-32','{}'::jsonb)"),{"id":str(outbox2),"tenant":str(TENANT)})
        with pytest.raises(DBAPIError):
            with db.session(tenant_id=TENANT) as session:
                session.execute(text("UPDATE audit_events SET action='changed' WHERE audit_id=:id"),{"id":str(audit)})
        with pytest.raises(DBAPIError):
            with db.session(tenant_id=OTHER) as session:
                session.execute(text("INSERT INTO investigations (investigation_id,tenant_id,incident_id,status,payload) VALUES (:id,:tenant,:incident,'created','{}'::jsonb)"),{"id":str(uuid4()),"tenant":str(OTHER),"incident":str(incident)})
    finally:
        db.dispose()
