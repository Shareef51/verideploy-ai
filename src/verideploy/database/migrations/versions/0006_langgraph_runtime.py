"""LangGraph production runtime metadata.

Revision ID: 0006_milestone18_langgraph_runtime
Revises: 0005_milestone17_video_evidence

LangGraph's official AsyncPostgresSaver owns its checkpoint tables. VeriDeploy owns
run metadata and replayable runtime events in these tenant-scoped tables.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_milestone18_langgraph_runtime"
down_revision = "0005_milestone17_video_evidence"
branch_labels = None
depends_on = None


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.create_table(
        "graph_runs",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.String(255), nullable=False),
        sa.Column("graph_name", sa.String(120), nullable=False),
        sa.Column("graph_version", sa.String(40), nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "run_id", name="uq_graph_run_tenant_run"),
        sa.UniqueConstraint("tenant_id", "thread_id", name="uq_graph_run_tenant_thread"),
    )
    op.create_table(
        "graph_runtime_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("graph_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("node_name", sa.String(160), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "run_id", "sequence_number", name="uq_graph_event_sequence"),
    )
    op.create_index("ix_graph_runs_tenant_status", "graph_runs", ["tenant_id", "status", "updated_at"])
    op.create_index("ix_graph_events_tenant_run_sequence", "graph_runtime_events", ["tenant_id", "run_id", "sequence_number"])
    _tenant_policy("graph_runs")
    _tenant_policy("graph_runtime_events")


def downgrade() -> None:
    op.drop_table("graph_runtime_events")
    op.drop_table("graph_runs")
