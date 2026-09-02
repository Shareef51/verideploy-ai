"""Immutable evidence versions, lineage, provenance and retention."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_milestone30_immutable_evidence"
down_revision = "0011_milestone29_synthetic_incidents"
branch_labels = None
depends_on = None

KINDS = ("document","image","audio","video","metric","log","trace","event","release","incident","analysis")
RELATIONS = ("derived_from","version_of","extracted_from","correlated_from")


def upgrade() -> None:
    op.create_table(
        "evidence_versions",
        sa.Column("record_id", sa.Uuid(), primary_key=True),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_derived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("object_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence_inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retention", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version >= 1", name="ck_evidence_version_positive"),
        sa.CheckConstraint(f"kind IN {KINDS}", name="ck_evidence_kind"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_evidence_content_hash"),
        sa.UniqueConstraint("tenant_id", "evidence_id", "version", name="uq_evidence_version"),
    )
    op.create_table(
        "evidence_parent_links",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_record_id", sa.Uuid(), sa.ForeignKey("evidence_versions.record_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("child_record_id", sa.Uuid(), sa.ForeignKey("evidence_versions.record_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"relation IN {RELATIONS}", name="ck_evidence_parent_relation"),
        sa.CheckConstraint("parent_record_id <> child_record_id", name="ck_evidence_no_self_parent"),
        sa.PrimaryKeyConstraint("child_record_id", "parent_record_id", name="pk_evidence_parent_link"),
    )
    op.create_index("ix_evidence_versions_tenant_evidence", "evidence_versions", ["tenant_id","evidence_id","version"])
    op.create_index("ix_evidence_versions_kind_time", "evidence_versions", ["tenant_id","kind","created_at"])
    op.create_index("ix_evidence_versions_hash", "evidence_versions", ["tenant_id","content_sha256"])
    op.create_index("ix_evidence_parent_parent", "evidence_parent_links", ["tenant_id","parent_record_id"])

    for table in ("evidence_versions", "evidence_parent_links"):
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        ))

    op.execute(sa.text("""
        CREATE FUNCTION forbid_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'immutable evidence rows cannot be updated or deleted';
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_immutable_versions BEFORE UPDATE OR DELETE ON evidence_versions FOR EACH ROW EXECUTE FUNCTION forbid_evidence_mutation()"))
    op.execute(sa.text("CREATE TRIGGER trg_immutable_parent_links BEFORE UPDATE OR DELETE ON evidence_parent_links FOR EACH ROW EXECUTE FUNCTION forbid_evidence_mutation()"))
    op.execute(sa.text("""
        CREATE FUNCTION validate_parent_tenant() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_tenant uuid; child_tenant uuid;
        BEGIN
          SELECT tenant_id INTO parent_tenant FROM evidence_versions WHERE record_id=NEW.parent_record_id;
          SELECT tenant_id INTO child_tenant FROM evidence_versions WHERE record_id=NEW.child_record_id;
          IF parent_tenant IS NULL OR child_tenant IS NULL OR parent_tenant <> NEW.tenant_id OR child_tenant <> NEW.tenant_id THEN
            RAISE EXCEPTION 'evidence parent/child tenant mismatch';
          END IF;
          RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_parent_tenant BEFORE INSERT ON evidence_parent_links FOR EACH ROW EXECUTE FUNCTION validate_parent_tenant()"))

    op.execute(sa.text("""
        CREATE FUNCTION validate_evidence_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE prev_record uuid;
        BEGIN
          IF NEW.version = 1 AND NEW.is_derived THEN
            IF NOT EXISTS (SELECT 1 FROM evidence_parent_links l WHERE l.child_record_id = NEW.record_id) THEN
              RAISE EXCEPTION 'derived evidence must have at least one parent';
            END IF;
          ELSIF NEW.version > 1 THEN
            SELECT record_id INTO prev_record FROM evidence_versions
              WHERE tenant_id=NEW.tenant_id AND evidence_id=NEW.evidence_id AND version=NEW.version-1;
            IF prev_record IS NULL OR NOT EXISTS (
              SELECT 1 FROM evidence_parent_links l
              WHERE l.child_record_id=NEW.record_id AND l.parent_record_id=prev_record AND l.relation='version_of'
            ) THEN
              RAISE EXCEPTION 'evidence version must link to the immediately previous version';
            END IF;
          END IF;
          RETURN NEW;
        END; $$
    """))
    op.execute(sa.text("""
        CREATE CONSTRAINT TRIGGER trg_lineage_complete
        AFTER INSERT ON evidence_versions DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_evidence_lineage()
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_lineage_complete ON evidence_versions"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_evidence_lineage()"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_parent_tenant ON evidence_parent_links"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_parent_tenant()"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_immutable_parent_links ON evidence_parent_links"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_immutable_versions ON evidence_versions"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS forbid_evidence_mutation()"))
    op.drop_table("evidence_parent_links")
    op.drop_table("evidence_versions")
