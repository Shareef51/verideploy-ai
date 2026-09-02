"""Self-corrective RAG runs and attempts."""
from alembic import op
import sqlalchemy as sa

revision = "0018_milestone36_self_corrective_rag"
down_revision = "0017_milestone35_metadata_filtering_authorization"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(sa.text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'''CREATE POLICY {table}_tenant_isolation ON {table}
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)'''))


def upgrade() -> None:
    op.create_table(
        "self_corrective_rag_runs",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("controller_version", sa.String(32), nullable=False),
        sa.Column("stop_reason", sa.String(80), nullable=False),
        sa.Column("answerable", sa.Boolean(), nullable=False),
        sa.Column("qualified", sa.Boolean(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("NOT (answerable AND qualified)", name="ck_answerable_not_qualified"),
    )
    op.create_index("ix_self_corrective_rag_runs_tenant_created", "self_corrective_rag_runs", ["tenant_id", "created_at"])
    op.create_index("ix_runs_tenant_stop", "self_corrective_rag_runs", ["tenant_id", "stop_reason", "created_at"])
    _rls("self_corrective_rag_runs")

    op.create_table(
        "self_corrective_rag_attempts",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("self_corrective_rag_runs.run_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("attempt_number", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("requested_scope_relaxed", sa.Boolean(), nullable=False),
        sa.Column("retrieval_run_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_grade", sa.String(32), nullable=False),
        sa.Column("evidence_score", sa.Float(), nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=True),
        sa.Column("attempt_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attempt_number >= 1 AND attempt_number <= 5", name="ck_attempt_number"),
        sa.CheckConstraint("evidence_score >= 0 AND evidence_score <= 1", name="ck_evidence_score"),
    )
    op.create_index("ix_attempts_tenant_run", "self_corrective_rag_attempts", ["tenant_id", "run_id", "attempt_number"])
    _rls("self_corrective_rag_attempts")

    op.execute(sa.text('''CREATE OR REPLACE FUNCTION prevent_self_corrective_rag_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'self-corrective RAG history is append-only'; END; $$ LANGUAGE plpgsql'''))
    for table in ("self_corrective_rag_runs", "self_corrective_rag_attempts"):
        op.execute(sa.text(f'''CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_self_corrective_rag_mutation()'''))

    op.execute(sa.text('''CREATE OR REPLACE FUNCTION validate_attempt_tenant() RETURNS trigger AS $$
    DECLARE parent_tenant uuid;
    BEGIN
      SELECT tenant_id INTO parent_tenant FROM self_corrective_rag_runs WHERE run_id=NEW.run_id;
      IF parent_tenant IS NULL OR parent_tenant <> NEW.tenant_id THEN
        RAISE EXCEPTION 'attempt tenant mismatch';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql'''))
    op.execute(sa.text('''CREATE TRIGGER trg_attempt_tenant BEFORE INSERT ON self_corrective_rag_attempts
        FOR EACH ROW EXECUTE FUNCTION validate_attempt_tenant()'''))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS self_corrective_rag_attempts CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS self_corrective_rag_runs CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_attempt_tenant() CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_self_corrective_rag_mutation() CASCADE"))
