from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from verideploy.graphs.durability import (
    CompensationStatus, InMemoryDurabilityRepository, LeaseConflictError, LeaseLostError,
    LongRunningWorkflowCoordinator, StepStatus,
)
from verideploy.graphs.memory_repository import InMemoryGraphRuntimeRepository
from verideploy.graphs.runtime import GraphDefinition, GraphRegistry, GraphRunStatus, LangGraphRuntime

TENANT=uuid4()

class FakeGraph:
    def __init__(self): self.state={}; self.invocations=0
    async def ainvoke(self,input,config=None,**kwargs): self.invocations+=1; self.state={**self.state,**input,"resumed_count":self.invocations}; return dict(self.state)
    async def aget_state(self,config): return dict(self.state)
    async def aupdate_state(self,config,state): self.state=dict(state)
    async def _stream(self):
        if False: yield None
    def astream(self,*args,**kwargs): return self._stream()

def runtime_pair():
    graph=FakeGraph(); registry=GraphRegistry(); registry.register(GraphDefinition(name='durable-demo',version='1',factory=lambda _:graph))
    rr=InMemoryGraphRuntimeRepository(); rt=LangGraphRuntime(registry=registry,repository=rr,checkpointer=object())
    return graph,rr,rt

def make_run(rr, *, status=GraphRunStatus.RUNNING):
    run_id=uuid4(); rr.create_run(tenant_id=TENANT,run_id=run_id,thread_id=str(run_id),graph_name='durable-demo',graph_version='1',correlation_id='corr-42'); rr.set_status(tenant_id=TENANT,run_id=run_id,status=status); return run_id


def test_lease_compare_and_swap_heartbeat_and_takeover_after_expiry():
    repo=InMemoryDurabilityRepository(); run=uuid4(); t=datetime(2026,1,1,tzinfo=timezone.utc)
    lease=repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='worker-a',ttl_seconds=10,now=t)
    renewed=repo.heartbeat(tenant_id=TENANT,run_id=run,owner_id='worker-a',lease_token=lease.lease_token,expected_version=1,ttl_seconds=10,now=t+timedelta(seconds=2))
    assert renewed.version==2
    with pytest.raises(LeaseLostError): repo.heartbeat(tenant_id=TENANT,run_id=run,owner_id='worker-a',lease_token=lease.lease_token,expected_version=1,ttl_seconds=10,now=t+timedelta(seconds=3))
    with pytest.raises(LeaseConflictError): repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='worker-b',ttl_seconds=10,now=t+timedelta(seconds=5))
    takeover=repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='worker-b',ttl_seconds=10,now=t+timedelta(seconds=13))
    assert takeover.owner_id=='worker-b' and takeover.version==3 and takeover.lease_token!=lease.lease_token


@pytest.mark.asyncio
async def test_completed_idempotent_step_is_not_reexecuted():
    _,rr,rt=runtime_pair(); run=make_run(rr); repo=InMemoryDurabilityRepository(); coord=LongRunningWorkflowCoordinator(runtime=rt,repository=repo,owner_id='w',lease_ttl_seconds=10,heartbeat_seconds=2)
    calls=0
    async def side_effect():
        nonlocal calls; calls+=1; return {'external_id':'DEP-42'}
    first=await coord.run_step(tenant_id=TENANT,run_id=run,step_key='deploy',idempotency_key='deploy:42',timeout_seconds=1,func=side_effect)
    second=await coord.run_step(tenant_id=TENANT,run_id=run,step_key='deploy',idempotency_key='deploy:42',timeout_seconds=1,func=side_effect)
    assert calls==1 and first.output_sha256==second.output_sha256 and second.status==StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_step_timeout_is_durable_and_retry_increments_attempt():
    _,rr,rt=runtime_pair(); run=make_run(rr); repo=InMemoryDurabilityRepository(); coord=LongRunningWorkflowCoordinator(runtime=rt,repository=repo,owner_id='w',lease_ttl_seconds=10,heartbeat_seconds=2)
    calls=0
    async def flaky():
        nonlocal calls; calls+=1
        if calls==1: await asyncio.sleep(.05)
        return {'ok':True}
    with pytest.raises(TimeoutError): await coord.run_step(tenant_id=TENANT,run_id=run,step_key='probe',idempotency_key='probe:1',timeout_seconds=.01,func=flaky)
    failed=repo.get_step(tenant_id=TENANT,run_id=run,idempotency_key='probe:1'); assert failed.status==StepStatus.FAILED and failed.error_code=='TimeoutError'
    done=await coord.run_step(tenant_id=TENANT,run_id=run,step_key='probe',idempotency_key='probe:1',timeout_seconds=.2,func=flaky)
    assert done.status==StepStatus.COMPLETED and done.attempt_number==2 and calls==2


@pytest.mark.asyncio
async def test_retry_exhaustion_runs_compensation_once():
    _,rr,rt=runtime_pair(); run=make_run(rr); repo=InMemoryDurabilityRepository(); coord=LongRunningWorkflowCoordinator(runtime=rt,repository=repo,owner_id='w',lease_ttl_seconds=10,heartbeat_seconds=2)
    attempts=0; compensated=0
    async def fail():
        nonlocal attempts; attempts+=1; raise RuntimeError('boom')
    async def compensate():
        nonlocal compensated; compensated+=1
    with pytest.raises(RuntimeError): await coord.run_step_with_retry(tenant_id=TENANT,run_id=run,step_key='write',idempotency_key='write:1',timeout_seconds=1,func=fail,max_attempts=3,backoff_seconds=0,compensation=compensate)
    step=repo.get_step(tenant_id=TENANT,run_id=run,idempotency_key='write:1')
    assert attempts==3 and compensated==1 and step.status==StepStatus.COMPENSATED and step.compensation_status==CompensationStatus.COMPLETED


def test_stuck_detection_excludes_approval_cancelled_and_completed_runs():
    _,rr,rt=runtime_pair(); repo=InMemoryDurabilityRepository(); coord=LongRunningWorkflowCoordinator(runtime=rt,repository=repo,owner_id='scanner',lease_ttl_seconds=10,heartbeat_seconds=2)
    now=datetime(2026,1,1,tzinfo=timezone.utc); expected=[]
    for status in [GraphRunStatus.RUNNING,GraphRunStatus.FAILED,GraphRunStatus.TIMED_OUT,GraphRunStatus.WAITING_FOR_APPROVAL,GraphRunStatus.CANCELLED,GraphRunStatus.COMPLETED]:
        run=make_run(rr,status=status); repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='dead',ttl_seconds=1,now=now)
        if status in {GraphRunStatus.RUNNING,GraphRunStatus.FAILED,GraphRunStatus.TIMED_OUT}: expected.append(run)
    found=coord.detect_stuck(tenant_id=TENANT,now=now+timedelta(seconds=2))
    assert {x.run_id for x in found}==set(expected)


@pytest.mark.asyncio
async def test_cancellation_blocks_lease_takeover_and_runtime_recovery():
    _,rr,rt=runtime_pair(); run=make_run(rr); repo=InMemoryDurabilityRepository(); coord=LongRunningWorkflowCoordinator(runtime=rt,repository=repo,owner_id='worker-a',lease_ttl_seconds=10,heartbeat_seconds=2)
    repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='worker-a',ttl_seconds=10)
    coord.cancel(tenant_id=TENANT,run_id=run,actor_id='operator',reason='incident closed'); rr.set_status(tenant_id=TENANT,run_id=run,status=GraphRunStatus.CANCELLED)
    with pytest.raises(LeaseConflictError): repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='worker-b',ttl_seconds=10,now=datetime.now(timezone.utc)+timedelta(seconds=20))
    with pytest.raises(LeaseConflictError): await coord.recover(tenant_id=TENANT,run_id=run)


@pytest.mark.asyncio
async def test_chaos_worker_death_recovers_same_run_without_duplicate_step_effect():
    graph,rr,rt=runtime_pair(); run=make_run(rr); repo=InMemoryDurabilityRepository(); now=datetime(2026,1,1,tzinfo=timezone.utc)
    # Worker A owns the run and commits a side effect, then dies: no lease release.
    repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='worker-a',ttl_seconds=1,now=now)
    coord_a=LongRunningWorkflowCoordinator(runtime=rt,repository=repo,owner_id='worker-a',lease_ttl_seconds=2,heartbeat_seconds=.5)
    calls=0
    async def effect():
        nonlocal calls; calls+=1; return {'ticket':'JIRA-42'}
    await coord_a.run_step(tenant_id=TENANT,run_id=run,step_key='create-ticket',idempotency_key='ticket:INC-42',timeout_seconds=1,func=effect)
    assert calls==1
    # Worker B sees the stale lease and takes over the exact persisted run/thread.
    coord_b=LongRunningWorkflowCoordinator(runtime=rt,repository=repo,owner_id='worker-b',lease_ttl_seconds=2,heartbeat_seconds=.5)
    stuck=coord_b.detect_stuck(tenant_id=TENANT,now=now+timedelta(seconds=2)); assert [x.run_id for x in stuck]==[run]
    repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='worker-b',ttl_seconds=2,now=now+timedelta(seconds=2))
    # Recovery asks for the same logical side effect; stored terminal output wins.
    recovered_step=await coord_b.run_step(tenant_id=TENANT,run_id=run,step_key='create-ticket',idempotency_key='ticket:INC-42',timeout_seconds=1,func=effect)
    assert calls==1 and recovered_step.output=={'ticket':'JIRA-42'}
    # Resume graph state on same run identity.
    repo.release_lease(tenant_id=TENANT,run_id=run,owner_id='worker-b',lease_token=repo.get_lease(tenant_id=TENANT,run_id=run).lease_token)
    record,result=await coord_b.recover(tenant_id=TENANT,run_id=run,timeout_seconds=1)
    assert record.run_id==run and result['run_id']==str(run) and graph.invocations==1


def test_operational_replay_is_deterministic_and_sequence_bounded():
    _,rr,rt=runtime_pair(); run=make_run(rr); repo=InMemoryDurabilityRepository(); coord=LongRunningWorkflowCoordinator(runtime=rt,repository=repo,owner_id='w',lease_ttl_seconds=10,heartbeat_seconds=2)
    lease=repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='w',ttl_seconds=10); repo.heartbeat(tenant_id=TENANT,run_id=run,owner_id='w',lease_token=lease.lease_token,expected_version=1,ttl_seconds=10)
    a=coord.operational_replay(tenant_id=TENANT,run_id=run); b=coord.operational_replay(tenant_id=TENANT,run_id=run)
    tail=coord.operational_replay(tenant_id=TENANT,run_id=run,from_sequence=1)
    assert a.replay_sha256==b.replay_sha256 and a.event_count==2 and tail.event_count==1


def test_migration_has_rls_idempotency_stuck_indexes_and_append_only_events():
    src=Path('src/verideploy/database/migrations/versions/0023_long_running_workflow_durability.py').read_text()
    for token in ['workflow_leases','workflow_steps','workflow_durability_events','uq_step_idempotency','ix_lease_stuck','FORCE ROW LEVEL SECURITY','validate_run_tenant','validate_step_transition','completed idempotent step is terminal','prevent_durability_event_mutation']:
        assert token in src
    repo=Path('src/verideploy/graphs/durability_repository.py').read_text()
    assert 'FOR UPDATE' in repo and 'expected_version' in repo and 'expires_at>:n' in repo


def test_version_config_factory_and_master_scope_wiring():
    from packaging.version import Version
    from verideploy import __version__
    assert Version(__version__) >= Version('0.42.0')
    config=Path('src/verideploy/config.py').read_text(); factory=Path('src/verideploy/graphs/factory.py').read_text()
    for token in ['workflow_lease_ttl_seconds','workflow_heartbeat_seconds','workflow_retry_max_attempts','WORKFLOW_HEARTBEAT_SECONDS must be less than WORKFLOW_LEASE_TTL_SECONDS']: assert token in config
    assert 'create_long_running_workflow_coordinator' in factory and 'PostgresDurabilityRepository' in factory

def test_private_durability_api_enforces_trusted_service_and_tenant_scope():
    from fastapi.testclient import TestClient
    from services.ai.main import app
    from services.ai.durability import WorkflowDurabilityOperations, get_workflow_durability_operations
    graph,rr,rt=runtime_pair(); run=make_run(rr)
    repo=InMemoryDurabilityRepository(); now=datetime.now(timezone.utc)-timedelta(seconds=5)
    repo.acquire_lease(tenant_id=TENANT,run_id=run,owner_id='dead-worker',ttl_seconds=1,now=now)
    ops=WorkflowDurabilityOperations(repo,rr); app.dependency_overrides[get_workflow_durability_operations]=lambda:ops
    client=TestClient(app)
    try:
        assert client.get('/internal/v1/workflows/durability/stuck',headers={'x-tenant-id':str(TENANT)}).status_code==401
        res=client.get('/internal/v1/workflows/durability/stuck',headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(TENANT)})
        assert res.status_code==200 and res.json()[0]['run_id']==str(run)
        replay=client.get(f'/internal/v1/workflows/durability/{run}/replay',headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(TENANT)})
        assert replay.status_code==200 and replay.json()['event_count']>=1
        cancel=client.post(f'/internal/v1/workflows/durability/{run}/cancel',json={'actor_id':'ops','reason':'operator requested'},headers={'x-internal-service':'verideploy-gateway','x-tenant-id':str(TENANT)})
        assert cancel.status_code==204 and rr.get_run(tenant_id=TENANT,run_id=run).status==GraphRunStatus.CANCELLED
    finally:
        app.dependency_overrides.clear()
