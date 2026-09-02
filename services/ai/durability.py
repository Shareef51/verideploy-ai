from __future__ import annotations
from functools import lru_cache
from datetime import datetime, timezone
from uuid import UUID

from verideploy.config import get_settings
from verideploy.database.factory import create_database_manager
from verideploy.graphs.durability import RecoveryCandidate, ReplayResult
from verideploy.graphs.durability_repository import PostgresDurabilityRepository
from verideploy.graphs.repository import SqlAlchemyGraphRuntimeRepository
from verideploy.graphs.runtime import GraphRunStatus

class WorkflowDurabilityOperations:
    def __init__(self,durability,graph_repo): self.durability=durability; self.graph_repo=graph_repo
    def stuck(self,*,tenant_id:UUID,now:datetime|None=None):
        now=now or datetime.now(timezone.utc); allowed={GraphRunStatus.RUNNING,GraphRunStatus.FAILED,GraphRunStatus.TIMED_OUT}
        return [c for c in self.durability.list_stuck(tenant_id=tenant_id,stale_before=now) if (r:=self.graph_repo.get_run(tenant_id=tenant_id,run_id=c.run_id)) is not None and r.status in allowed]
    def replay(self,*,tenant_id:UUID,run_id:UUID,from_sequence:int=0)->ReplayResult:
        events=self.durability.events(tenant_id=tenant_id,run_id=run_id,after_sequence=from_sequence)
        from verideploy.graphs.durability import _sha
        payload=[{"sequence":e.sequence,"event_type":e.event_type,"payload":e.payload,"occurred_at":e.occurred_at.isoformat()} for e in events]
        return ReplayResult(tenant_id=tenant_id,run_id=run_id,from_sequence=from_sequence,event_count=len(events),state_event_types=[e.event_type for e in events],replay_sha256=_sha({"tenant_id":str(tenant_id),"run_id":str(run_id),"events":payload}))
    def cancel(self,*,tenant_id:UUID,run_id:UUID,actor_id:str,reason:str):
        run=self.graph_repo.get_run(tenant_id=tenant_id,run_id=run_id)
        if run is None: raise KeyError('graph run not found')
        self.durability.cancel_run(tenant_id=tenant_id,run_id=run_id,actor_id=actor_id,reason=reason)
        if run.status not in {GraphRunStatus.COMPLETED,GraphRunStatus.CANCELLED}:
            self.graph_repo.set_status(tenant_id=tenant_id,run_id=run_id,status=GraphRunStatus.CANCELLED,error_code='operator_cancelled')
            self.graph_repo.append_event(tenant_id=tenant_id,run_id=run_id,thread_id=run.thread_id,graph_name=run.graph_name,graph_version=run.graph_version,event_type='graph.run.cancelled',payload={'actor_id':actor_id,'reason':reason,'source':'durability'})

@lru_cache
def get_workflow_durability_operations()->WorkflowDurabilityOperations:
    settings=get_settings()
    if not settings.database_url.startswith('postgresql'): raise RuntimeError('workflow durability requires PostgreSQL')
    db=create_database_manager(settings)
    return WorkflowDurabilityOperations(PostgresDurabilityRepository(db,statement_timeout_ms=settings.db_statement_timeout_ms),SqlAlchemyGraphRuntimeRepository(db,statement_timeout_ms=settings.db_statement_timeout_ms))
