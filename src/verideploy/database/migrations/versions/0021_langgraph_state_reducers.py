"""Versioned LangGraph state and replay metadata.

Revision ID: 0021_milestone39_langgraph_state_reducers
Revises: 0020_milestone38_citation_architecture
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021_milestone39_langgraph_state_reducers"
down_revision = "0020_milestone38_citation_architecture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_state_snapshots",
        sa.Column("snapshot_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("graph_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("investigation_id", sa.String(128), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("snapshot_kind", sa.String(40), nullable=False),
        sa.Column("state_schema_version", sa.Integer(), nullable=False),
        sa.Column("serializer_version", sa.String(80), nullable=False),
        sa.Column("encryption_policy_version", sa.String(80), nullable=False),
        sa.Column("state_sha256", sa.String(64), nullable=False),
        sa.Column("migration_history", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sequence >= 1", name="ck_snapshot_sequence"),
        sa.CheckConstraint("state_schema_version >= 1", name="ck_state_schema_version"),
        sa.CheckConstraint("char_length(state_sha256) = 64", name="ck_milestone39_state_sha256"),
        sa.CheckConstraint("snapshot_kind IN ('input','checkpoint_migrated','result','replay')", name="ck_snapshot_kind"),
        sa.UniqueConstraint("tenant_id", "run_id", "sequence", name="uq_snapshot_sequence"),
    )
    op.create_index("ix_state_run_sequence", "graph_state_snapshots", ["tenant_id", "run_id", "sequence"])
    op.create_index("ix_state_investigation", "graph_state_snapshots", ["tenant_id", "investigation_id", "created_at"])
    op.execute("ALTER TABLE graph_state_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE graph_state_snapshots FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY graph_state_snapshots_tenant_isolation
        ON graph_state_snapshots
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE FUNCTION prevent_state_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'saved investigation state is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_state_immutable
        BEFORE UPDATE OR DELETE ON graph_state_snapshots
        FOR EACH ROW EXECUTE FUNCTION prevent_state_mutation()
    """)
    op.execute("""
        CREATE FUNCTION validate_state_run_tenant() RETURNS trigger AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM graph_runs r
             WHERE r.run_id = NEW.run_id AND r.tenant_id = NEW.tenant_id
          ) THEN
            RAISE EXCEPTION 'state/run tenant mismatch';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_state_run_tenant
        BEFORE INSERT ON graph_state_snapshots
        FOR EACH ROW EXECUTE FUNCTION validate_state_run_tenant()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_state_run_tenant ON graph_state_snapshots")
    op.execute("DROP FUNCTION IF EXISTS validate_state_run_tenant()")
    op.execute("DROP TRIGGER IF EXISTS trg_state_immutable ON graph_state_snapshots")
    op.execute("DROP FUNCTION IF EXISTS prevent_state_mutation()")
    op.drop_table("graph_state_snapshots")
