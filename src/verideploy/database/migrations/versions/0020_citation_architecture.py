"""Stable citation architecture."""
from alembic import op
import sqlalchemy as sa

revision="0020_milestone38_citation_architecture"
down_revision="0019_milestone37_hallucination_protection"
branch_labels=None
depends_on=None


def _rls(table:str)->None:
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f'''CREATE POLICY {table}_tenant_isolation ON {table}
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)'''))


def upgrade()->None:
    op.create_table(
        "citations",
        sa.Column("citation_id",sa.Uuid(),primary_key=True),
        sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("document_id",sa.Uuid(),sa.ForeignKey("retrieval_documents.document_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("chunk_id",sa.Uuid(),sa.ForeignKey("retrieval_chunks.chunk_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("source_key",sa.String(240),nullable=False),
        sa.Column("title",sa.String(500),nullable=False),
        sa.Column("source_version",sa.String(128),nullable=False),
        sa.Column("evidence_sha256",sa.String(64),nullable=False),
        sa.Column("locator_kind",sa.String(24),nullable=False),
        sa.Column("locator_json",sa.JSON(),nullable=False),
        sa.Column("required_permission",sa.String(160),nullable=False),
        sa.Column("service",sa.String(120)),sa.Column("environment",sa.String(80)),sa.Column("team",sa.String(160)),sa.Column("document_kind",sa.String(64)),
        sa.Column("deep_link",sa.String(500),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False),
        sa.CheckConstraint("evidence_sha256 ~ '^[0-9a-f]{64}$'",name="ck_citation_sha"),
        sa.CheckConstraint("locator_kind IN ('text','page','timecode','code')",name="ck_locator_kind"),
    )
    op.create_index("ix_citations_tenant_document","citations",["tenant_id","document_id","created_at"])
    op.create_index("ix_citations_tenant_chunk","citations",["tenant_id","chunk_id"])
    _rls("citations")

    op.create_table(
        "claim_citations",
        sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),primary_key=True),
        sa.Column("verification_id",sa.Uuid(),sa.ForeignKey("hallucination_protection_runs.verification_id",ondelete="RESTRICT"),primary_key=True),
        sa.Column("claim_id",sa.String(128),primary_key=True),
        sa.Column("citation_id",sa.Uuid(),sa.ForeignKey("citations.citation_id",ondelete="RESTRICT"),primary_key=True),
        sa.Column("entailment_score",sa.Float(),nullable=False),
        sa.Column("entails_released_claim",sa.Boolean(),nullable=False),
        sa.Column("claim_qualified",sa.Boolean(),nullable=False,server_default=sa.text("false")),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False),
        sa.CheckConstraint("entailment_score >= 0 AND entailment_score <= 1",name="ck_entailment_score"),
    )
    op.create_index("ix_claim_citations_lookup","claim_citations",["tenant_id","verification_id","claim_id"])
    _rls("claim_citations")

    op.execute(sa.text('''CREATE OR REPLACE FUNCTION prevent_citation_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'citation history is append-only'; END; $$ LANGUAGE plpgsql'''))
    for table in ("citations","claim_citations"):
        op.execute(sa.text(f'''CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_citation_mutation()'''))

    op.execute(sa.text('''CREATE OR REPLACE FUNCTION validate_citation_source_tenant() RETURNS trigger AS $$
    DECLARE doc_tenant uuid; chunk_tenant uuid;
    BEGIN
      SELECT tenant_id INTO doc_tenant FROM retrieval_documents WHERE document_id=NEW.document_id;
      SELECT tenant_id INTO chunk_tenant FROM retrieval_chunks WHERE chunk_id=NEW.chunk_id AND document_id=NEW.document_id;
      IF doc_tenant IS NULL OR chunk_tenant IS NULL OR doc_tenant<>NEW.tenant_id OR chunk_tenant<>NEW.tenant_id THEN
        RAISE EXCEPTION 'citation source tenant mismatch';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql'''))
    op.execute(sa.text('''CREATE TRIGGER trg_citation_source_tenant BEFORE INSERT ON citations
        FOR EACH ROW EXECUTE FUNCTION validate_citation_source_tenant()'''))

    op.execute(sa.text('''CREATE OR REPLACE FUNCTION validate_mapping_tenant() RETURNS trigger AS $$
    DECLARE verification_tenant uuid; citation_tenant uuid;
    BEGIN
      SELECT tenant_id INTO verification_tenant FROM hallucination_protection_runs WHERE verification_id=NEW.verification_id;
      SELECT tenant_id INTO citation_tenant FROM citations WHERE citation_id=NEW.citation_id;
      IF verification_tenant IS NULL OR citation_tenant IS NULL OR verification_tenant<>NEW.tenant_id OR citation_tenant<>NEW.tenant_id THEN
        RAISE EXCEPTION 'citation mapping tenant mismatch';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql'''))
    op.execute(sa.text('''CREATE TRIGGER trg_mapping_tenant BEFORE INSERT ON claim_citations
        FOR EACH ROW EXECUTE FUNCTION validate_mapping_tenant()'''))


def downgrade()->None:
    op.execute(sa.text("DROP TABLE IF EXISTS claim_citations CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS citations CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_mapping_tenant() CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_citation_source_tenant() CASCADE"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_citation_mutation() CASCADE"))
