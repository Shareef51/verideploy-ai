from __future__ import annotations
import json
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from verideploy.database.session import DatabaseManager
from .core import AuditActor, AuditEvent, AuditResult, AuditSearchQuery, AuditTrail, ActorType, RetentionClass, _event_body

class SqlAuditRepository:
    metadata=sa.MetaData()
    table=sa.Table('audit_compliance_events',metadata,
      sa.Column('audit_id',sa.Uuid(),primary_key=True), sa.Column('tenant_id',sa.Uuid(),nullable=False), sa.Column('sequence',sa.BigInteger(),nullable=False),
      sa.Column('occurred_at',sa.DateTime(timezone=True),nullable=False), sa.Column('actor_type',sa.String(24),nullable=False), sa.Column('actor_id',sa.String(256),nullable=False), sa.Column('actor_roles',JSONB,nullable=False), sa.Column('service_id',sa.String(160)),
      sa.Column('action',sa.String(256),nullable=False), sa.Column('result',sa.String(24),nullable=False), sa.Column('resource_type',sa.String(128),nullable=False), sa.Column('resource_id',sa.String(256),nullable=False),
      sa.Column('correlation_id',sa.String(256),nullable=False), sa.Column('trace_id',sa.String(64)), sa.Column('span_id',sa.String(32)), sa.Column('source',sa.String(160),nullable=False), sa.Column('reason_code',sa.String(120)), sa.Column('payload',JSONB,nullable=False),
      sa.Column('retention_class',sa.String(32),nullable=False), sa.Column('retain_until',sa.DateTime(timezone=True),nullable=False), sa.Column('legal_hold',sa.Boolean(),nullable=False),
      sa.Column('previous_hash',sa.String(64),nullable=False), sa.Column('event_hash',sa.String(64),nullable=False), sa.Column('review_signature',JSONB),
    )
    def __init__(self,database_url:str): self.db=DatabaseManager(database_url)
    def append(self,event:AuditEvent)->None:
        v={
          'audit_id':event.audit_id,'tenant_id':event.tenant_id,'sequence':event.sequence,'occurred_at':event.occurred_at,'actor_type':event.actor.actor_type.value,'actor_id':event.actor.actor_id,'actor_roles':list(event.actor.roles),'service_id':event.actor.service_id,
          'action':event.action,'result':event.result.value,'resource_type':event.resource.resource_type,'resource_id':event.resource.resource_id,'correlation_id':event.correlation_id,'trace_id':event.trace_id,'span_id':event.span_id,'source':event.source,'reason_code':event.reason_code,'payload':dict(event.payload),
          'retention_class':event.retention_class.value,'retain_until':event.retain_until,'legal_hold':event.legal_hold,'previous_hash':event.previous_hash,'event_hash':event.event_hash,'review_signature':event.review_signature.__dict__ if event.review_signature else None}
        with self.db.transaction(event.tenant_id) as s: s.execute(sa.insert(self.table).values(**v))
    def search(self,q:AuditSearchQuery)->list[dict]:
        stmt=sa.select(self.table).where(self.table.c.tenant_id==q.tenant_id).order_by(self.table.c.occurred_at.desc(),self.table.c.sequence.desc()).limit(min(max(q.limit,1),1000))
        if q.actor_id: stmt=stmt.where(self.table.c.actor_id==q.actor_id)
        if q.action: stmt=stmt.where(self.table.c.action==q.action)
        if q.resource_type: stmt=stmt.where(self.table.c.resource_type==q.resource_type)
        if q.resource_id: stmt=stmt.where(self.table.c.resource_id==q.resource_id)
        if q.result: stmt=stmt.where(self.table.c.result==q.result.value)
        if q.correlation_id: stmt=stmt.where(self.table.c.correlation_id==q.correlation_id)
        if q.from_time: stmt=stmt.where(self.table.c.occurred_at>=q.from_time)
        if q.to_time: stmt=stmt.where(self.table.c.occurred_at<=q.to_time)
        with self.db.transaction(q.tenant_id) as s: return [dict(r) for r in s.execute(stmt).mappings().all()]
