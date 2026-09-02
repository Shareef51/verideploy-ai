"""Supervisor, planner, and agent-run persistence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_milestone19_agent_contracts"
down_revision = "0006_milestone18_langgraph_runtime"
branch_labels = None
depends_on = None


def _tenant_policy(table: str) -> None:
    op.execute(sa.text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY'))
    op.execute(sa.text(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    ))


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_name", sa.String(40), nullable=False),
        sa.Column("prompt_name", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("max_tool_calls >= 0 AND max_tool_calls <= 64", name="ck_agent_run_max_tool_calls"),
        sa.CheckConstraint("tool_calls_used >= 0 AND tool_calls_used <= max_tool_calls", name="ck_agent_run_tool_budget"),
    )
    op.create_index("ix_agent_runs_tenant_agent_status", "agent_runs", ["tenant_id", "agent_name", "status", "updated_at"])
    op.create_index("ix_agent_runs_prompt_hash", "agent_runs", ["tenant_id", "prompt_sha256", "input_sha256"])
    _tenant_policy("agent_runs")


def downgrade() -> None:
    op.drop_table("agent_runs")
