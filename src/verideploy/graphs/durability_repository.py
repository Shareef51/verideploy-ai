from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
import hashlib, json
from sqlalchemy import text
from verideploy.database.session import DatabaseManager
from verideploy.graphs.durability import (
    CompensationStatus, DurableStep, DurabilityEvent, LeaseConflictError, LeaseLostError,
    RecoveryCandidate, StepConflictError, StepStatus, WorkflowLease,
)


def _lease(row: Any) -> WorkflowLease:
    m=row._mapping
    return WorkflowLease(**{k:m[k] for k in WorkflowLease.model_fields})

def _step(row: Any) -> DurableStep:
    m=row._mapping
    return DurableStep(step_id=m['step_id'],tenant_id=m['tenant_id'],run_id=m['run_id'],step_key=m['step_key'],idempotency_key=m['idempotency_key'],status=StepStatus(m['status']),attempt_number=m['attempt_number'],timeout_seconds=m['timeout_seconds'],output=m['output_json'],output_sha256=m['output_sha256'],error_code=m['error_code'],compensation_status=CompensationStatus(m['compensation_status']),started_at=m['started_at'],completed_at=m['completed_at'],updated_at=m['updated_at'])

class PostgresDurabilityRepository:
    def __init__(self,database:DatabaseManager,*,statement_timeout_ms:int=15000): self.database=database; self.statement_timeout_ms=statement_timeout_ms
    def _event(self,session,tenant_id,run_id,event_type,payload):
        seq=session.execute(text("SELECT COALESCE(MAX(sequence),0)+1 FROM workflow_durability_events WHERE tenant_id=:t AND run_id=:r"),{"t":tenant_id,"r":run_id}).scalar_one()
        session.execute(text("INSERT INTO workflow_durability_events(event_id,tenant_id,run_id,sequence,event_type,payload,occurred_at) VALUES(:id,:t,:r,:s,:e,CAST(:p AS jsonb),now())"),{"id":uuid4(),"t":tenant_id,"r":run_id,"s":seq,"e":event_type,"p":json.dumps(payload,default=str)})
    def acquire_lease(self,*,tenant_id,run_id,owner_id,ttl_seconds,now=None):
        now=now or datetime.now(timezone.utc)
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            row=s.execute(text("SELECT * FROM workflow_leases WHERE tenant_id=:t AND run_id=:r FOR UPDATE"),{"t":tenant_id,"r":run_id}).first()
            if row:
                cur=_lease(row)
                if cur.cancelled_at is not None: raise LeaseConflictError('run is cancelled')
                if cur.expires_at>now and cur.owner_id!=owner_id: raise LeaseConflictError('run lease is owned by another worker')
                version=cur.version+1; token=uuid4(); acquired=now
                s.execute(text("UPDATE workflow_leases SET owner_id=:o,lease_token=:tok,version=:v,acquired_at=:n,heartbeat_at=:n,expires_at=:x,cancelled_at=NULL WHERE tenant_id=:t AND run_id=:r"),{"o":owner_id,"tok":token,"v":version,"n":now,"x":now+timedelta(seconds=ttl_seconds),"t":tenant_id,"r":run_id})
            else:
                version=1; token=uuid4(); acquired=now
                s.execute(text("INSERT INTO workflow_leases(lease_id,tenant_id,run_id,owner_id,lease_token,version,acquired_at,heartbeat_at,expires_at) VALUES(:id,:t,:r,:o,:tok,1,:n,:n,:x)"),{"id":uuid4(),"t":tenant_id,"r":run_id,"o":owner_id,"tok":token,"n":now,"x":now+timedelta(seconds=ttl_seconds)})
            self._event(s,tenant_id,run_id,'workflow.lease.acquired',{'owner_id':owner_id,'version':version}); s.commit()
        return self.get_lease(tenant_id=tenant_id,run_id=run_id)
    def heartbeat(self,*,tenant_id,run_id,owner_id,lease_token,expected_version,ttl_seconds,now=None):
        now=now or datetime.now(timezone.utc)
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            result=s.execute(text("UPDATE workflow_leases SET version=version+1,heartbeat_at=:n,expires_at=:x WHERE tenant_id=:t AND run_id=:r AND owner_id=:o AND lease_token=:tok AND version=:v AND cancelled_at IS NULL AND expires_at>:n RETURNING *"),{"n":now,"x":now+timedelta(seconds=ttl_seconds),"t":tenant_id,"r":run_id,"o":owner_id,"tok":lease_token,"v":expected_version}).first()
            if not result: raise LeaseLostError('workflow lease lost or expired')
            lease=_lease(result); self._event(s,tenant_id,run_id,'workflow.lease.heartbeat',{'owner_id':owner_id,'version':lease.version}); s.commit(); return lease
    def release_lease(self,*,tenant_id,run_id,owner_id,lease_token):
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            s.execute(text("UPDATE workflow_leases SET expires_at=LEAST(expires_at,now()) WHERE tenant_id=:t AND run_id=:r AND owner_id=:o AND lease_token=:tok"),{"t":tenant_id,"r":run_id,"o":owner_id,"tok":lease_token}); self._event(s,tenant_id,run_id,'workflow.lease.released',{'owner_id':owner_id}); s.commit()
    def get_lease(self,*,tenant_id,run_id):
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            row=s.execute(text("SELECT * FROM workflow_leases WHERE tenant_id=:t AND run_id=:r"),{"t":tenant_id,"r":run_id}).first(); return _lease(row) if row else None
    def cancel_run(self,*,tenant_id,run_id,actor_id,reason):
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            s.execute(text("UPDATE workflow_leases SET cancelled_at=COALESCE(cancelled_at,now()),version=version+1 WHERE tenant_id=:t AND run_id=:r"),{"t":tenant_id,"r":run_id}); self._event(s,tenant_id,run_id,'workflow.run.cancelled',{'actor_id':actor_id,'reason':reason}); s.commit()
        return self.get_lease(tenant_id=tenant_id,run_id=run_id)
    def list_stuck(self,*,tenant_id,stale_before):
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            rows=s.execute(text("SELECT run_id,owner_id,expires_at FROM workflow_leases l JOIN graph_runs g USING(run_id) WHERE l.tenant_id=:t AND l.cancelled_at IS NULL AND l.expires_at<=:b AND g.status IN ('RUNNING','FAILED','TIMED_OUT') ORDER BY l.expires_at, l.run_id"),{"t":tenant_id,"b":stale_before}).all()
            return [RecoveryCandidate(tenant_id=tenant_id,run_id=r.run_id,previous_owner_id=r.owner_id,lease_expired_at=r.expires_at) for r in rows]
    def get_step(self,*,tenant_id,run_id,idempotency_key):
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            row=s.execute(text("SELECT * FROM workflow_steps WHERE tenant_id=:t AND run_id=:r AND idempotency_key=:i"),{"t":tenant_id,"r":run_id,"i":idempotency_key}).first(); return _step(row) if row else None
    def begin_step(self,*,tenant_id,run_id,step_key,idempotency_key,timeout_seconds,now=None):
        now=now or datetime.now(timezone.utc)
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            row=s.execute(text("SELECT * FROM workflow_steps WHERE tenant_id=:t AND run_id=:r AND idempotency_key=:i FOR UPDATE"),{"t":tenant_id,"r":run_id,"i":idempotency_key}).first()
            if row:
                cur=_step(row)
                if cur.status==StepStatus.COMPLETED: return cur
                if cur.status==StepStatus.RUNNING: raise StepConflictError('step already running')
                s.execute(text("UPDATE workflow_steps SET status='running',attempt_number=attempt_number+1,step_key=:k,timeout_seconds=:to,started_at=:n,completed_at=NULL,error_code=NULL,updated_at=:n WHERE tenant_id=:t AND run_id=:r AND idempotency_key=:i"),{"k":step_key,"to":timeout_seconds,"n":now,"t":tenant_id,"r":run_id,"i":idempotency_key})
            else:
                s.execute(text("INSERT INTO workflow_steps(step_id,tenant_id,run_id,step_key,idempotency_key,status,attempt_number,timeout_seconds,compensation_status,started_at,updated_at) VALUES(:id,:t,:r,:k,:i,'running',1,:to,'none',:n,:n)"),{"id":uuid4(),"t":tenant_id,"r":run_id,"k":step_key,"i":idempotency_key,"to":timeout_seconds,"n":now})
            self._event(s,tenant_id,run_id,'workflow.step.started',{'step_key':step_key,'idempotency_key':idempotency_key}); s.commit()
        return self.get_step(tenant_id=tenant_id,run_id=run_id,idempotency_key=idempotency_key)
    def complete_step(self,*,tenant_id,run_id,idempotency_key,output):
        raw=json.dumps(output,sort_keys=True,separators=(',',':'),default=str); digest=hashlib.sha256(raw.encode()).hexdigest()
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            row=s.execute(text("UPDATE workflow_steps SET status='completed',output_json=CAST(:o AS jsonb),output_sha256=:h,completed_at=now(),updated_at=now(),error_code=NULL WHERE tenant_id=:t AND run_id=:r AND idempotency_key=:i AND status='running' RETURNING *"),{"o":raw,"h":digest,"t":tenant_id,"r":run_id,"i":idempotency_key}).first()
            if not row: raise StepConflictError('step is not running')
            self._event(s,tenant_id,run_id,'workflow.step.completed',{'idempotency_key':idempotency_key,'output_sha256':digest}); s.commit(); return _step(row)
    def fail_step(self,*,tenant_id,run_id,idempotency_key,error_code,compensation_required):
        cs='required' if compensation_required else 'none'
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            row=s.execute(text("UPDATE workflow_steps SET status='failed',error_code=:e,compensation_status=:c,updated_at=now() WHERE tenant_id=:t AND run_id=:r AND idempotency_key=:i RETURNING *"),{"e":error_code,"c":cs,"t":tenant_id,"r":run_id,"i":idempotency_key}).first()
            if not row: raise KeyError('step not found')
            self._event(s,tenant_id,run_id,'workflow.step.failed',{'idempotency_key':idempotency_key,'error_code':error_code,'compensation_required':compensation_required}); s.commit(); return _step(row)
    def compensate_step(self,*,tenant_id,run_id,idempotency_key,success):
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            row=s.execute(text("UPDATE workflow_steps SET status=CASE WHEN :ok THEN 'compensated' ELSE status END,compensation_status=CASE WHEN :ok THEN 'completed' ELSE 'failed' END,updated_at=now() WHERE tenant_id=:t AND run_id=:r AND idempotency_key=:i AND compensation_status IN ('required','running') RETURNING *"),{"ok":success,"t":tenant_id,"r":run_id,"i":idempotency_key}).first()
            if not row: raise StepConflictError('compensation not required')
            self._event(s,tenant_id,run_id,'workflow.step.compensated' if success else 'workflow.step.compensation_failed',{'idempotency_key':idempotency_key}); s.commit(); return _step(row)
    def events(self,*,tenant_id,run_id,after_sequence=0):
        with self.database.tenant_session(tenant_id,statement_timeout_ms=self.statement_timeout_ms) as s:
            rows=s.execute(text("SELECT * FROM workflow_durability_events WHERE tenant_id=:t AND run_id=:r AND sequence>:a ORDER BY sequence"),{"t":tenant_id,"r":run_id,"a":after_sequence}).all()
            return [DurabilityEvent(event_id=x.event_id,tenant_id=x.tenant_id,run_id=x.run_id,sequence=x.sequence,event_type=x.event_type,payload=x.payload,occurred_at=x.occurred_at) for x in rows]
