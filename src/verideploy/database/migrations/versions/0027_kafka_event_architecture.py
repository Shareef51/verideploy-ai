"""Kafka event architecture outbox/inbox.
Revision ID: 0027_milestone65_kafka_event_architecture
Revises: 0026_milestone63_audit_compliance_trail
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0027_milestone65_kafka_event_architecture'; down_revision='0026_milestone63_audit_compliance_trail'; branch_labels=None; depends_on=None


def upgrade():
    op.create_table('event_outbox',
      sa.Column('outbox_id',sa.Uuid(),primary_key=True),sa.Column('tenant_id',sa.Uuid(),nullable=False),sa.Column('topic',sa.String(256),nullable=False),sa.Column('ordering_key',sa.String(256),nullable=False),sa.Column('aggregate_id',sa.String(256),nullable=False),sa.Column('event_id',sa.Uuid(),nullable=False),sa.Column('sequence_number',sa.BigInteger(),nullable=False),sa.Column('schema_family',sa.String(160),nullable=False),sa.Column('schema_version',sa.String(32),nullable=False),sa.Column('payload',postgresql.JSONB(),nullable=False),sa.Column('headers',postgresql.JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('now()')),sa.Column('published_at',sa.DateTime(timezone=True)),sa.Column('attempts',sa.Integer(),nullable=False,server_default='0'),sa.Column('last_error',sa.Text()),sa.UniqueConstraint('event_id',name='uq_outbox_event'))
    op.create_index('ix_outbox_pending','event_outbox',['published_at','created_at'])
    op.create_index('ix_outbox_order','event_outbox',['tenant_id','ordering_key','sequence_number'])
    op.create_table('event_inbox',
      sa.Column('consumer_group',sa.String(256),nullable=False),sa.Column('event_id',sa.Uuid(),nullable=False),sa.Column('tenant_id',sa.Uuid(),nullable=False),sa.Column('aggregate_id',sa.String(256),nullable=False),sa.Column('sequence_number',sa.BigInteger(),nullable=False),sa.Column('topic',sa.String(256),nullable=False),sa.Column('partition',sa.Integer(),nullable=False),sa.Column('offset',sa.BigInteger(),nullable=False),sa.Column('processed_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('now()')),sa.Column('result',sa.String(32),nullable=False),sa.PrimaryKeyConstraint('consumer_group','event_id',name='pk_inbox'),sa.UniqueConstraint('consumer_group','tenant_id','aggregate_id','sequence_number',name='uq_inbox_sequence'))
    op.create_index('ix_inbox_replay','event_inbox',['tenant_id','aggregate_id','sequence_number'])
    op.create_table('event_replay_requests',
      sa.Column('replay_id',sa.Uuid(),primary_key=True),sa.Column('tenant_id',sa.Uuid(),nullable=False),sa.Column('topic',sa.String(256),nullable=False),sa.Column('aggregate_id',sa.String(256)),sa.Column('from_sequence',sa.BigInteger(),nullable=False),sa.Column('requested_by',sa.String(256),nullable=False),sa.Column('reason',sa.Text(),nullable=False),sa.Column('status',sa.String(32),nullable=False,server_default='requested'),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('now()')),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False))
    for table in ('event_outbox','event_inbox','event_replay_requests'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'); op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY {table}_tenant ON {table} USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)")


def downgrade():
    op.drop_table('event_replay_requests'); op.drop_table('event_inbox'); op.drop_table('event_outbox')
