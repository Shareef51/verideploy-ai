"""Hallucination protection verification history."""
from alembic import op
import sqlalchemy as sa

revision = "0019_milestone37_hallucination_protection"
down_revision = "0018_milestone36_self_corrective_rag"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f'''CREATE POLICY {table}_tenant_isolation ON {table}
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)'''))


def upgrade() -> None:
    op.create_table(
        "hallucination_protection_runs",
        sa.Column("verification_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("self_corrective_run_id", sa.Uuid(), sa.ForeignKey("self_corrective_rag_runs.run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("verifier_version", sa.String(32), nullable=False),
        sa.Column("protected", sa.Boolean(), nullable=False),
        sa.Column("supported_count", sa.Integer(), nullable=False),
        sa.Column("uncertain_count", sa.Integer(), nullable=False),
        sa.Column("unsupported_count", sa.Integer(), nullable=False),
        sa.Column("unsupported_material_rate", sa.Float(), nullable=False),
        sa.Column("prompt_injection_evidence_count", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("supported_count >= 0 AND uncertain_count >= 0 AND unsupported_count >= 0", name="ck_claim_counts"),
        sa.CheckConstraint("unsupported_material_rate >= 0 AND unsupported_material_rate <= 1", name="ck_unsupported_rate"),
        sa.CheckConstraint("prompt_injection_evidence_count >= 0", name="ck_injection_count"),
    )
    op.create_index("ix_hallucination_protection_runs_tenant_created", "hallucination_protection_runs", ["tenant_id", "created_at"])
    op.create_index("ix_runs_tenant_source", "hallucination_protection_runs", ["tenant_id", "self_corrective_run_id"])
    _rls("hallucination_protection_runs")

    op.create_table(
        "hallucination_claim_verifications",
        sa.Column("verification_id", sa.Uuid(), sa.ForeignKey("hallucination_protection_runs.verification_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("claim_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("material", sa.Boolean(), nullable=False),
        sa.Column("proposed_confidence", sa.Float(), nullable=False),
        sa.Column("adjusted_confidence", sa.Float(), nullable=False),
        sa.Column("claim_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("label IN ('supported','unsupported','uncertain')", name="ck_claim_label"),
        sa.CheckConstraint("action IN ('keep','remove','qualify')", name="ck_claim_action"),
        sa.CheckConstraint("proposed_confidence >= 0 AND proposed_confidence <= 1", name="ck_proposed_confidence"),
        sa.CheckConstraint("adjusted_confidence >= 0 AND adjusted_confidence <= 1", name="ck_adjusted_confidence"),
    )
    op.create_index("ix_claims_tenant_label", "hallucination_claim_verifications", ["tenant_id", "label", "created_at"])
    _rls("hallucination_claim_verifications")

    op.execute(sa.text('''CREATE OR REPLACE FUNCTION prevent_hallucination_protection_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'hallucination verification history is append-only'; END; $$ LANGUAGE plpgsql'''))
    for table in ("hallucination_protection_runs", "hallucination_claim_verifications"):
        op.execute(sa.text(f'''CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_hallucination_protection_mutation()'''))

    op.execute(sa.text('''CREATE OR REPLACE FUNCTION validate_claim_tenant() RETURNS trigger AS $$
    DECLARE parent_tenant uuid;
    BEGIN
      SELECT tenant_id INTO parent_tenant FROM hallucination_protection_runs WHERE verification_id=NEW.verification_id;
      IF parent_tenant IS NULL OR parent_tenant <> NEW.tenant_id THEN
        RAISE EXCEPTION 'claim tenant mismatch';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql'''))
    op.execute(sa.text('''CREATE TRIGGER trg_claim_tenant BEFORE INSERT ON hallucination_claim_verifications
        FOR EACH ROW EXECUTE FUNCTION validate_claim_tenant()'''))

    op.execute(sa.text('''CREATE OR REPLACE FUNCTION validate_source_tenant() RETURNS trigger AS $$
    DECLARE source_tenant uuid;
    BEGIN
      SELECT tenant_id INTO source_tenant FROM self_corrective_rag_runs WHERE run_id=NEW.self_corrective_run_id;
      IF source_tenant IS NULL OR source_tenant <> NEW.tenant_id THEN
        RAISE EXCEPTION 'source run tenant mismatch';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql'''))
    op.execute(sa.text('''CREATE TRIGGER trg_source_tenant BEFORE INSERT ON hallucination_protection_runs
        FOR EACH ROW EXECUTE FUNCTION validate_source_tenant()'''))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS hallucination_claim_verifications CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS hallucination_protection_runs CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_source_tenant() CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_claim_tenant() CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_hallucination_protection_mutation() CASCADE"))
