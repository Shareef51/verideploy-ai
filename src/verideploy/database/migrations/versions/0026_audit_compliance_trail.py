"""Audit and compliance trail.
Revision ID: 0026_milestone63_audit_compliance_trail
Revises: 0025_milestone48_llmops_data_platform
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0026_milestone63_audit_compliance_trail'; down_revision='0025_milestone48_llmops_data_platform'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('audit_compliance_events',
      sa.Column('audit_id',sa.Uuid(),primary_key=True),sa.Column('tenant_id',sa.Uuid(),nullable=False),sa.Column('sequence',sa.BigInteger(),nullable=False),sa.Column('occurred_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('now()')),
      sa.Column('actor_type',sa.String(24),nullable=False),sa.Column('actor_id',sa.String(256),nullable=False),sa.Column('actor_roles',postgresql.JSONB(),nullable=False,server_default=sa.text("'[]'::jsonb")),sa.Column('service_id',sa.String(160)),
      sa.Column('action',sa.String(256),nullable=False),sa.Column('result',sa.String(24),nullable=False),sa.Column('resource_type',sa.String(128),nullable=False),sa.Column('resource_id',sa.String(256),nullable=False),sa.Column('correlation_id',sa.String(256),nullable=False),sa.Column('trace_id',sa.String(64)),sa.Column('span_id',sa.String(32)),sa.Column('source',sa.String(160),nullable=False),sa.Column('reason_code',sa.String(120)),sa.Column('payload',postgresql.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")),
      sa.Column('retention_class',sa.String(32),nullable=False),sa.Column('retain_until',sa.DateTime(timezone=True),nullable=False),sa.Column('legal_hold',sa.Boolean(),nullable=False,server_default=sa.text('false')),sa.Column('previous_hash',sa.String(64),nullable=False),sa.Column('event_hash',sa.String(64),nullable=False),sa.Column('review_signature',postgresql.JSONB()),
      sa.CheckConstraint("actor_type IN ('user','service','agent','system')",name='ck_actor'),sa.CheckConstraint("result IN ('succeeded','denied','failed','cancelled')",name='ck_result'),sa.UniqueConstraint('tenant_id','sequence',name='uq_tenant_sequence'),sa.UniqueConstraint('tenant_id','event_hash',name='uq_tenant_event_hash'))
    op.create_index('ix_audit_search','audit_compliance_events',['tenant_id','occurred_at','resource_type','resource_id'])
    op.create_index('ix_audit_corr','audit_compliance_events',['tenant_id','correlation_id','occurred_at'])
    op.execute('ALTER TABLE audit_compliance_events ENABLE ROW LEVEL SECURITY'); op.execute('ALTER TABLE audit_compliance_events FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY audit_events_tenant ON audit_compliance_events USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)")
    op.execute("CREATE FUNCTION block_audit_compliance_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='DELETE' AND current_setting('app.audit_retention_purge',true)='on' AND OLD.legal_hold=false AND OLD.retain_until<=now() THEN RETURN OLD; END IF; RAISE EXCEPTION 'audit events are append-only'; END $$")
    op.execute("CREATE TRIGGER trg_audit_immutable BEFORE UPDATE OR DELETE ON audit_compliance_events FOR EACH ROW EXECUTE FUNCTION block_audit_compliance_mutation()")

def downgrade():
    op.execute('DROP TRIGGER IF EXISTS trg_audit_immutable ON audit_compliance_events'); op.execute('DROP FUNCTION IF EXISTS block_audit_compliance_mutation()'); op.drop_table('audit_compliance_events')
