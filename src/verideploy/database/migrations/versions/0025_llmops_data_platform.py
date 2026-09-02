"""LLMOps data platform.
Revision ID: 0025_milestone48_llmops_data_platform
Revises: 0024_milestone45_release_risk_screen
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0025_milestone48_llmops_data_platform'; down_revision='0024_milestone45_release_risk_screen'; branch_labels=None; depends_on=None
def upgrade():
    op.create_table('llmops_events',
      sa.Column('event_id',sa.Uuid(),primary_key=True),sa.Column('tenant_id',sa.Uuid(),nullable=False),sa.Column('correlation_id',sa.String(128),nullable=False),sa.Column('investigation_id',sa.Uuid()),sa.Column('graph_run_id',sa.Uuid()),sa.Column('agent_run_id',sa.Uuid()),sa.Column('retrieval_run_id',sa.Uuid()),sa.Column('tool_invocation_id',sa.Uuid()),sa.Column('kind',sa.String(32),nullable=False),sa.Column('operation',sa.String(160),nullable=False),sa.Column('prompt_name',sa.String(120)),sa.Column('prompt_version',sa.String(64)),sa.Column('prompt_sha256',sa.String(64)),sa.Column('model_role',sa.String(40)),sa.Column('model_name',sa.String(160)),sa.Column('input_tokens',sa.Integer(),nullable=False,server_default='0'),sa.Column('output_tokens',sa.Integer(),nullable=False,server_default='0'),sa.Column('total_tokens',sa.Integer(),nullable=False,server_default='0'),sa.Column('latency_ms',sa.Float(),nullable=False,server_default='0'),sa.Column('cost_usd',sa.Numeric(18,8),nullable=False,server_default='0'),sa.Column('tool_name',sa.String(160)),sa.Column('retrieval_count',sa.Integer(),nullable=False,server_default='0'),sa.Column('retry_count',sa.Integer(),nullable=False,server_default='0'),sa.Column('failure_code',sa.String(120)),sa.Column('confidence',sa.Float()),sa.Column('payload_json',postgresql.JSONB(astext_type=sa.Text()),nullable=False,server_default=sa.text("'{}'::jsonb")),sa.Column('retention_class',sa.String(40),nullable=False,server_default='operational_90d'),sa.Column('occurred_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('now()')),sa.CheckConstraint('input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0 AND retry_count >= 0 AND retrieval_count >= 0','ck_nonnegative'),sa.CheckConstraint('confidence IS NULL OR (confidence >= 0 AND confidence <= 1)','ck_confidence'))
    op.create_index('ix_correlation_trace','llmops_events',['tenant_id','correlation_id','occurred_at'])
    op.create_index('ix_investigation_trace','llmops_events',['tenant_id','investigation_id','occurred_at'])
    op.create_index('ix_retention','llmops_events',['tenant_id','retention_class','occurred_at'])
    op.execute('ALTER TABLE llmops_events ENABLE ROW LEVEL SECURITY'); op.execute('ALTER TABLE llmops_events FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY llmops_events_tenant ON llmops_events USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)")
    op.execute("CREATE FUNCTION prevent_llmops_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='DELETE' AND current_setting('app.retention_purge', true)='on' THEN RETURN OLD; END IF; RAISE EXCEPTION 'llmops events are append-only'; END $$")
    op.execute("CREATE TRIGGER trg_llmops_immutable BEFORE UPDATE OR DELETE ON llmops_events FOR EACH ROW EXECUTE FUNCTION prevent_llmops_mutation()")
def downgrade():
    op.execute('DROP TRIGGER IF EXISTS trg_llmops_immutable ON llmops_events'); op.execute('DROP FUNCTION IF EXISTS prevent_llmops_mutation()'); op.drop_table('llmops_events')
