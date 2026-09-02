from __future__ import annotations
import json
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text

from verideploy.database.performance.budgets import QueryBudget, QueryBudgetError
from verideploy.database.performance.telemetry import SlowQueryTelemetry, sql_fingerprint
from verideploy.database.performance.plans import ExplainPlanPolicy, evaluate_explain_plan
from verideploy.database.session import DatabaseManager

MIG=Path('src/verideploy/database/migrations/versions/0015_postgres_performance_reliability.py')
ENV=Path('src/verideploy/database/migrations/env.py')
LOAD=Path('config/load/postgres-load.json')


def test_query_budget_validates_timeout_order_and_bounds():
    budget=QueryBudget(10_000, 500, 20_000)
    assert budget.lock_timeout_ms < budget.statement_timeout_ms
    with pytest.raises(QueryBudgetError): QueryBudget(1_000, 2_000, 10_000)
    with pytest.raises(QueryBudgetError): QueryBudget(99, 50, 1_000)


def test_database_manager_keeps_pooling_and_per_transaction_budgets():
    db=DatabaseManager('sqlite+pysqlite:///:memory:', pool_recycle_seconds=60)
    with db.tenant_session(uuid4(), budget=QueryBudget()) as session:
        assert session.execute(text('SELECT 1')).scalar_one()==1
    assert isinstance(db.pool_status(), str)
    db.dispose()


def test_slow_query_telemetry_uses_fingerprint_not_bound_values():
    telemetry=SlowQueryTelemetry(threshold_ms=10)
    statement="SELECT * FROM incidents WHERE tenant_id='11111111-1111-1111-1111-111111111111' AND severity='SEV1' AND id=42"
    assert telemetry.record(statement,duration_ms=9.9) is None
    sample=telemetry.record(statement,duration_ms=11.0,rowcount=2)
    assert sample is not None and sample.operation=='SELECT'
    assert len(sample.fingerprint)==64
    assert '11111111' not in sample.fingerprint and 'SEV1' not in sample.fingerprint
    assert sample.fingerprint==sql_fingerprint(statement)


def test_explain_plan_policy_accepts_index_plan_and_rejects_large_seq_scan():
    policy=ExplainPlanPolicy(max_execution_ms=100,max_total_cost=1000,forbid_seq_scan_above_rows=10000)
    good=[{'Plan':{'Node Type':'Index Scan','Relation Name':'incidents','Plan Rows':20,'Total Cost':40},'Execution Time':4.2}]
    bad=[{'Plan':{'Node Type':'Seq Scan','Relation Name':'jobs','Plan Rows':50000,'Total Cost':2000},'Execution Time':170}]
    assert evaluate_explain_plan(good,policy).accepted is True
    result=evaluate_explain_plan(bad,policy)
    assert result.accepted is False
    assert set(result.reasons)=={'execution_time_exceeded','plan_cost_exceeded','large_sequential_scan'}


def test_migration_adds_targeted_indexes_partitioned_telemetry_and_rls():
    source=MIG.read_text()
    for token in ('ix_incidents_open_service_started','ix_jobs_ready','ix_outbox_unpublished','ix_retrieval_chunks_source','ix_graph_edges_relation_time'):
        assert token in source
    assert 'PARTITION BY RANGE (observed_at)' in source
    assert 'database_query_telemetry_default PARTITION OF' in source
    assert 'FORCE ROW LEVEL SECURITY' in source
    assert 'pg_stat_statements' in source


def test_migration_is_chained_and_reversible_without_dropping_shared_extension():
    source=MIG.read_text()
    assert 'down_revision = "0014_milestone32_complete_operational_schema"' in source
    assert 'DROP TABLE IF EXISTS database_query_telemetry CASCADE' in source
    assert 'DROP EXTENSION' not in source


def test_alembic_online_path_uses_bounded_advisory_migration_lock():
    source=ENV.read_text()
    assert 'postgres_migration_lock' in source
    assert 'DB_MIGRATION_LOCK_TIMEOUT_SECONDS' in source
    lock=Path('src/verideploy/database/migration_lock.py').read_text()
    assert 'pg_try_advisory_lock' in lock and 'pg_advisory_unlock' in lock
    assert 'MigrationLockTimeout' in lock


def test_load_fixture_defines_concurrency_and_plan_thresholds():
    cfg=json.loads(LOAD.read_text())
    assert cfg['query_workers'] >= 8
    assert cfg['incidents_per_tenant'] >= 1000
    assert cfg['thresholds']['p95_ms'] <= 200
    assert cfg['thresholds']['error_rate'] <= 0.01
    assert cfg['thresholds']['forbid_seq_scan_above_rows'] >= 10000


def test_configuration_exposes_pool_query_and_slow_query_budgets():
    source=Path('src/verideploy/config.py').read_text()
    env=Path('.env.example').read_text()
    for token in ('db_lock_timeout_ms','db_idle_in_transaction_timeout_ms','db_pool_recycle_seconds','db_slow_query_threshold_ms','db_migration_lock_timeout_seconds'):
        assert token in source
    for token in ('DB_LOCK_TIMEOUT_MS','DB_IDLE_IN_TRANSACTION_TIMEOUT_MS','DB_POOL_RECYCLE_SECONDS','DB_SLOW_QUERY_THRESHOLD_MS','DB_MIGRATION_LOCK_TIMEOUT_SECONDS'):
        assert token in env


def test_database_factory_propagates_performance_configuration():
    source=Path('src/verideploy/database/factory.py').read_text()
    for token in ('settings.db_pool_size','settings.db_max_overflow','settings.db_pool_timeout_seconds','settings.db_pool_recycle_seconds','settings.db_slow_query_threshold_ms'):
        assert token in source


def test_partition_default_is_also_forced_rls_for_direct_access():
    source=MIG.read_text()
    assert 'database_query_telemetry_default ENABLE ROW LEVEL SECURITY' in source
    assert 'database_query_telemetry_default FORCE ROW LEVEL SECURITY' in source
    assert 'database_query_telemetry_default_tenant_isolation' in source
