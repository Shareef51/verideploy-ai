from __future__ import annotations
import json
from copy import deepcopy
from uuid import UUID
from sqlalchemy import text
from verideploy.database.session import DatabaseManager
from .schemas import LLMOpsEvent

class InMemoryLLMOpsRepository:
    def __init__(self): self.items=[]
    def append(self,event): self.items.append(event.model_copy(deep=True))
    def purge_before(self,*,tenant_id,before):
        old=len(self.items); self.items=[x for x in self.items if not (x.tenant_id==tenant_id and x.occurred_at < before)]; return old-len(self.items)
    def list_by_correlation(self,*,tenant_id,correlation_id): return [x.model_copy(deep=True) for x in self.items if x.tenant_id==tenant_id and x.correlation_id==correlation_id]

class PostgresLLMOpsRepository:
    def __init__(self,db:DatabaseManager): self.db=db
    def append(self,event:LLMOpsEvent):
        d=event.model_dump(mode='json'); payload=json.dumps(d.pop('payload'),sort_keys=True,separators=(',',':'))
        cols=', '.join(d.keys())+', payload_json'; vals=', '.join(':'+k for k in d.keys())+', CAST(:payload_json AS jsonb)'
        with self.db.tenant_session(event.tenant_id) as s:
            s.execute(text(f'INSERT INTO llmops_events ({cols}) VALUES ({vals}) ON CONFLICT (event_id) DO NOTHING'),{**d,'payload_json':payload}); s.commit()
    def purge_before(self,*,tenant_id:UUID,before):
        with self.db.tenant_session(tenant_id) as s:
            s.execute(text("SELECT set_config('app.retention_purge','on',true)")); result=s.execute(text('DELETE FROM llmops_events WHERE tenant_id=:t AND occurred_at < :b'),{'t':str(tenant_id),'b':before}); s.commit(); return result.rowcount
    def list_by_correlation(self,*,tenant_id:UUID,correlation_id:str):
        with self.db.tenant_session(tenant_id) as s:
            rows=s.execute(text('SELECT * FROM llmops_events WHERE tenant_id=:t AND correlation_id=:c ORDER BY occurred_at,event_id'),{'t':str(tenant_id),'c':correlation_id}).mappings().all()
        out=[]
        for r in rows:
            d=dict(r); d['payload']=d.pop('payload_json') or {}; out.append(LLMOpsEvent.model_validate(d))
        return out
