"""MCP secure gateway audit persistence."""
from alembic import op
import sqlalchemy as sa

revision = "0009_milestone25_mcp_gateway"
down_revision = "0008_milestone20_rag_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_tool_audit",
        sa.Column("audit_id", sa.Uuid(), primary_key=True),
        sa.Column("invocation_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(160), nullable=False),
        sa.Column("service_name", sa.String(120), nullable=False),
        sa.Column("tool_name", sa.String(160), nullable=False),
        sa.Column("server_name", sa.String(80), nullable=False),
        sa.Column("permission", sa.String(120), nullable=False),
        sa.Column("risk", sa.String(20), nullable=False),
        sa.Column("effect", sa.String(20), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("arguments_sha256", sa.String(64), nullable=False),
        sa.Column("approval_id", sa.String(160), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("risk IN ('low','medium','high','critical')", name="ck_mcp_audit_risk"),
        sa.CheckConstraint("effect IN ('read','write')", name="ck_mcp_audit_effect"),
        sa.CheckConstraint("decision IN ('allowed','denied','failed')", name="ck_mcp_audit_decision"),
    )
    op.create_index("ix_mcp_audit_tenant_created", "mcp_tool_audit", ["tenant_id", "created_at"])
    op.create_index("ix_mcp_audit_tool_decision", "mcp_tool_audit", ["tenant_id", "tool_name", "decision", "created_at"])
    op.execute(sa.text("ALTER TABLE mcp_tool_audit ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE mcp_tool_audit FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY mcp_tool_audit_tenant_isolation ON mcp_tool_audit "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    ))


def downgrade() -> None:
    op.drop_table("mcp_tool_audit")
