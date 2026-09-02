from __future__ import annotations
import asyncio, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid5
from verideploy.graphs.durability import InMemoryDurabilityRepository, LongRunningWorkflowCoordinator
from verideploy.graphs.memory_repository import InMemoryGraphRuntimeRepository
from verideploy.graphs.runtime import GraphDefinition, GraphRegistry, GraphRunStatus, LangGraphRuntime

NS=UUID('b66da830-a132-49c7-9d27-f31190159a82'); TENANT=uuid5(NS,'tenant'); RUN=uuid5(NS,'run')
class Graph:
    def __init__(self): self.state={}; self.invocations=0
    async def ainvoke(self,input,config=None,**kwargs): self.invocations+=1; self.state={**self.state,**input,'recovered':True}; return dict(self.state)
    async def aget_state(self,config): return dict(self.state)
    async def aupdate_state(self,config,state): self.state=dict(state)
    async def _stream(self):
        if False: yield None
    def astream(self,*a,**k): return self._stream()

async def main():
    graph=Graph(); registry=GraphRegistry(); registry.register(GraphDefinition(name='chaos',version='1',factory=lambda _:graph)); rr=InMemoryGraphRuntimeRepository(); rr.create_run(tenant_id=TENANT,run_id=RUN,thread_id=str(RUN),graph_name='chaos',graph_version='1',correlation_id='chaos'); rr.set_status(tenant_id=TENANT,run_id=RUN,status=GraphRunStatus.RUNNING)
    repo=InMemoryDurabilityRepository(); t0=datetime(2026,8,18,12,0,tzinfo=timezone.utc); lease_a=repo.acquire_lease(tenant_id=TENANT,run_id=RUN,owner_id='worker-a',ttl_seconds=1,now=t0)
    a=LongRunningWorkflowCoordinator(runtime=LangGraphRuntime(registry=registry,repository=rr,checkpointer=object()),repository=repo,owner_id='worker-a',lease_ttl_seconds=2,heartbeat_seconds=.5)
    calls=0
    async def effect():
        nonlocal calls; calls+=1; return {'external_operation_id':'EXT-P42'}
    await a.run_step(tenant_id=TENANT,run_id=RUN,step_key='external-write',idempotency_key=':external-write',timeout_seconds=1,func=effect)
    # Simulated SIGKILL: worker A never releases lease.
    b=LongRunningWorkflowCoordinator(runtime=a.runtime,repository=repo,owner_id='worker-b',lease_ttl_seconds=2,heartbeat_seconds=.5)
    stuck=b.detect_stuck(tenant_id=TENANT,now=t0+timedelta(seconds=2))
    lease_b=repo.acquire_lease(tenant_id=TENANT,run_id=RUN,owner_id='worker-b',ttl_seconds=2,now=t0+timedelta(seconds=2))
    step=await b.run_step(tenant_id=TENANT,run_id=RUN,step_key='external-write',idempotency_key=':external-write',timeout_seconds=1,func=effect)
    repo.release_lease(tenant_id=TENANT,run_id=RUN,owner_id='worker-b',lease_token=lease_b.lease_token)
    record,result=await b.recover(tenant_id=TENANT,run_id=RUN,timeout_seconds=1)
    replay=b.operational_replay(tenant_id=TENANT,run_id=RUN)
    out={'valid':calls==1 and [x.run_id for x in stuck]==[RUN] and record.run_id==RUN and result.get('recovered') is True,'worker_a_lease_token':str(lease_a.lease_token),'worker_b_lease_token':str(lease_b.lease_token),'stuck_detected':len(stuck)==1,'side_effect_calls':calls,'idempotent_step_status':step.status.value,'recovered_run_id':str(record.run_id),'graph_invocations_after_recovery':graph.invocations,'durability_event_count':replay.event_count,'replay_sha256':replay.replay_sha256}
    Path('artifacts').mkdir(exist_ok=True); Path('artifacts/workflow-durability-validation.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps(out,indent=2,sort_keys=True))
    if not out['valid']: raise SystemExit(1)
asyncio.run(main())
