from __future__ import annotations
import json, os, statistics, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from alembic import command
from alembic.config import Config
from verideploy.database.performance.plans import ExplainPlanPolicy, evaluate_explain_plan

URL=os.getenv('TEST_POSTGRES_URL')
pytestmark=pytest.mark.skipif(not URL, reason='TEST_POSTGRES_URL is not configured')


def _migrate():
    cfg=Config('alembic.ini'); cfg.set_main_option('sqlalchemy.url', URL); command.upgrade(cfg,'head')


def test_explain_and_concurrency_thresholds():
    assert URL
    _migrate()
    engine=create_engine(URL,pool_size=8,max_overflow=8,pool_pre_ping=True)
    tenant=uuid4()
    with engine.begin() as c:
        c.execute(text("INSERT INTO tenants (tenant_id,name,created_at) VALUES (:id,'postgres-performance-live',now()) ON CONFLICT DO NOTHING"),{'id':tenant})
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"),{'t':str(tenant)})
        for i in range(1500):
            c.execute(text("INSERT INTO incidents (incident_id,tenant_id,external_key,service_id,severity,status,started_at,payload) VALUES (:id,:t,:k,:s,'SEV2',:st,now()-(:n||' seconds')::interval,'{}'::jsonb) ON CONFLICT DO NOTHING"),{'id':uuid4(),'t':tenant,'k':f'p33-{i}','s':uuid4(),'st':'open' if i%5==0 else 'resolved','n':i})
        explain=c.execute(text("EXPLAIN (ANALYZE, FORMAT JSON) SELECT incident_id FROM incidents WHERE tenant_id=:t AND service_id=(SELECT service_id FROM incidents WHERE tenant_id=:t LIMIT 1) AND status IN ('open','mitigating') ORDER BY started_at DESC LIMIT 20"),{'t':tenant}).scalar_one()
    if isinstance(explain,str): explain=json.loads(explain)
    policy_cfg=json.loads(Path('config/load/postgres-load.json').read_text())['thresholds']
    policy=ExplainPlanPolicy(policy_cfg['explain_max_execution_ms'],policy_cfg['explain_max_total_cost'],policy_cfg['forbid_seq_scan_above_rows'])
    assert evaluate_explain_plan(explain,policy).accepted

    def query_once(_):
        started=time.perf_counter()
        try:
            with engine.connect() as c:
                c.execute(text("SELECT set_config('app.tenant_id', :t, false)"),{'t':str(tenant)})
                c.execute(text("SET statement_timeout='1000ms'"))
                c.execute(text("SELECT incident_id FROM incidents WHERE tenant_id=:t AND status IN ('open','mitigating') ORDER BY started_at DESC LIMIT 25"),{'t':tenant}).all()
            return (time.perf_counter()-started)*1000,None
        except Exception as exc:
            return (time.perf_counter()-started)*1000,exc
    with ThreadPoolExecutor(max_workers=16) as pool:
        results=list(pool.map(query_once, range(160)))
    durations=sorted(r[0] for r in results)
    errors=[r for r in results if r[1] is not None]
    p95=durations[max(0,int(len(durations)*.95)-1)]
    assert len(errors)/len(results) <= policy_cfg['error_rate']
    assert p95 <= policy_cfg['p95_ms']
    engine.dispose()
