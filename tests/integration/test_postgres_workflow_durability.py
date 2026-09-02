from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from verideploy.database.session import DatabaseManager
from verideploy.graphs.durability import LeaseConflictError, LeaseLostError, StepStatus
from verideploy.graphs.durability_repository import PostgresDurabilityRepository

URL=os.getenv('TEST_POSTGRES_URL')
pytestmark=pytest.mark.skipif(not URL,reason='TEST_POSTGRES_URL is required for PostgreSQL durability tests')
def _sync(url:str)->str: return url.replace('postgresql+asyncpg://','postgresql+psycopg://').replace('postgresql://','postgresql+psycopg://',1)

def test_postgres_lease_idempotency_rls_and_append_only_recovery():
    assert URL; url=_sync(URL); cfg=Config('alembic.ini');cfg.set_main_option('sqlalchemy.url',url);command.upgrade(cfg,'head')
    tenant,other,run=uuid4(),uuid4(),uuid4(); engine=create_engine(url)
    with engine.begin() as c:
        for t in (tenant,other): c.execute(text('INSERT INTO tenants(tenant_id,slug,display_name) VALUES(:id,:slug,:name) ON CONFLICT DO NOTHING'),{'id':t,'slug':f'p42-{str(t)[:8]}','name':'postgres-workflow-durability'})
        c.execute(text("INSERT INTO graph_runs(run_id,tenant_id,thread_id,graph_name,graph_version,correlation_id,status,last_sequence,created_at,updated_at) VALUES(:r,:t,:th,'p42','1','corr','RUNNING',0,now(),now())"),{'r':run,'t':tenant,'th':str(run)})
    engine.dispose(); db=DatabaseManager(url); repo=PostgresDurabilityRepository(db); now=datetime.now(timezone.utc)
    lease=repo.acquire_lease(tenant_id=tenant,run_id=run,owner_id='worker-a',ttl_seconds=2,now=now)
    with pytest.raises(LeaseConflictError): repo.acquire_lease(tenant_id=tenant,run_id=run,owner_id='worker-b',ttl_seconds=2,now=now+timedelta(seconds=.5))
    renewed=repo.heartbeat(tenant_id=tenant,run_id=run,owner_id='worker-a',lease_token=lease.lease_token,expected_version=lease.version,ttl_seconds=2,now=now+timedelta(seconds=.5)); assert renewed.version==2
    with pytest.raises(LeaseLostError): repo.heartbeat(tenant_id=tenant,run_id=run,owner_id='worker-a',lease_token=lease.lease_token,expected_version=1,ttl_seconds=2,now=now+timedelta(seconds=.7))
    takeover=repo.acquire_lease(tenant_id=tenant,run_id=run,owner_id='worker-b',ttl_seconds=2,now=now+timedelta(seconds=3)); assert takeover.owner_id=='worker-b'
    repo.begin_step(tenant_id=tenant,run_id=run,step_key='external-write',idempotency_key='write:42',timeout_seconds=30)
    done=repo.complete_step(tenant_id=tenant,run_id=run,idempotency_key='write:42',output={'id':'ext-42'}); assert done.status==StepStatus.COMPLETED
    same=repo.begin_step(tenant_id=tenant,run_id=run,step_key='external-write',idempotency_key='write:42',timeout_seconds=30); assert same.status==StepStatus.COMPLETED
    assert repo.get_lease(tenant_id=other,run_id=run) is None
    with db.tenant_session(tenant) as s:
        eid=s.execute(text('SELECT event_id FROM workflow_durability_events WHERE run_id=:r ORDER BY sequence LIMIT 1'),{'r':run}).scalar_one()
        with pytest.raises(DBAPIError,match='append-only'):
            s.execute(text("UPDATE workflow_durability_events SET event_type='mutated' WHERE event_id=:id"),{'id':eid}); s.commit()
        s.rollback()
        with pytest.raises(DBAPIError,match='terminal'):
            s.execute(text("UPDATE workflow_steps SET status='failed' WHERE run_id=:r AND idempotency_key='write:42'"),{'r':run}); s.commit()
        s.rollback()
    db.dispose()
