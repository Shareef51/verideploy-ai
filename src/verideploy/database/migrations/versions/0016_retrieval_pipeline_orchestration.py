"""Traceable retrieval pipeline orchestration."""
from alembic import op
import sqlalchemy as sa

revision = "0016_milestone34_retrieval_pipeline_orchestration"
down_revision = "0015_milestone33_postgres_performance_reliability"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    ))


def upgrade() -> None:
    op.create_table(
        "retrieval_pipeline_runs",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("trace_json", sa.JSON(), nullable=False),
        sa.Column("context_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(input_sha256)=64", name="ck_run_input_hash"),
        sa.CheckConstraint("length(context_sha256)=64", name="ck_run_context_hash"),
    )
    op.create_index("ix_retrieval_pipeline_runs_tenant_created", "retrieval_pipeline_runs", ["tenant_id", "created_at"])
    op.create_index("ix_runs_input_hash", "retrieval_pipeline_runs", ["tenant_id", "input_sha256"])
    _rls("retrieval_pipeline_runs")

    op.create_table(
        "retrieval_ranking_decisions",
        sa.Column("decision_id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("retrieval_pipeline_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("source_key", sa.String(512), nullable=True),
        sa.Column("input_score", sa.Float(), nullable=True),
        sa.Column("output_score", sa.Float(), nullable=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("run_id", "stage", "ordinal", name="uq_run_stage_ordinal"),
        sa.CheckConstraint("ordinal > 0", name="ck_decision_ordinal"),
        sa.CheckConstraint("action IN ('keep','drop','score','select')", name="ck_decision_action"),
    )
    op.create_index("ix_decisions_run_stage", "retrieval_ranking_decisions", ["tenant_id", "run_id", "stage", "ordinal"])
    op.create_index("ix_decisions_chunk", "retrieval_ranking_decisions", ["tenant_id", "chunk_id", "created_at"])
    _rls("retrieval_ranking_decisions")

    op.execute(sa.text("""
    CREATE OR REPLACE FUNCTION prevent_trace_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'retrieval traces are append-only';
    END; $$ LANGUAGE plpgsql
    """))
    for table in ("retrieval_pipeline_runs", "retrieval_ranking_decisions"):
        op.execute(sa.text(f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION prevent_trace_mutation()"))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS retrieval_ranking_decisions CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS retrieval_pipeline_runs CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_trace_mutation()"))
