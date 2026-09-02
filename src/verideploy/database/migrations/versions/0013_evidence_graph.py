"""Tenant-isolated relational evidence graph."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_milestone31_evidence_graph"
down_revision = "0012_milestone30_immutable_evidence"
branch_labels = None
depends_on = None

ENTITY_TYPES=("pull_request","commit","release","service","incident","root_cause","evidence","team","environment")
RELATIONSHIPS=("modifies_service","contains_commit","deployed_as","experienced_incident","caused_by","supported_by","correlates_with","derived_from","occurred_before","depends_on","owned_by","runs_in")


def upgrade() -> None:
    op.create_table(
        "graph_entities",
        sa.Column("entity_id",sa.Uuid(),primary_key=True),
        sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("entity_type",sa.String(40),nullable=False),
        sa.Column("natural_key",sa.String(512),nullable=False),
        sa.Column("label",sa.String(512),nullable=False),
        sa.Column("reference_uri",sa.String(2048),nullable=False),
        sa.Column("evidence_record_id",sa.Uuid(),sa.ForeignKey("evidence_versions.record_id",ondelete="RESTRICT"),nullable=True),
        sa.Column("attributes",postgresql.JSONB(astext_type=sa.Text()),nullable=False,server_default=sa.text("'{}'::jsonb")),
        sa.Column("observed_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint(f"entity_type IN {ENTITY_TYPES}",name="ck_graph_entity_type"),
        sa.UniqueConstraint("tenant_id","entity_type","natural_key",name="uq_graph_entity_natural_key"),
    )
    op.create_table(
        "graph_edges",
        sa.Column("edge_id",sa.Uuid(),primary_key=True),
        sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("source_entity_id",sa.Uuid(),sa.ForeignKey("graph_entities.entity_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("target_entity_id",sa.Uuid(),sa.ForeignKey("graph_entities.entity_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("relationship",sa.String(48),nullable=False),
        sa.Column("confidence",sa.Float(),nullable=False),
        sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("valid_from",sa.DateTime(timezone=True),nullable=True),
        sa.Column("valid_to",sa.DateTime(timezone=True),nullable=True),
        sa.Column("attributes",postgresql.JSONB(astext_type=sa.Text()),nullable=False,server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint(f"relationship IN {RELATIONSHIPS}",name="ck_graph_relationship"),
        sa.CheckConstraint("source_entity_id <> target_entity_id",name="ck_graph_no_self_edge"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0",name="ck_graph_confidence"),
        sa.CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",name="ck_graph_temporal_window"),
    )
    op.create_index("ix_graph_entities_tenant_type", "graph_entities", ["tenant_id","entity_type","natural_key"])
    op.create_index("ix_graph_entities_evidence_record", "graph_entities", ["tenant_id","evidence_record_id"])
    op.create_index("ix_graph_edges_source", "graph_edges", ["tenant_id","source_entity_id","relationship"])
    op.create_index("ix_graph_edges_target", "graph_edges", ["tenant_id","target_entity_id","relationship"])
    op.create_index("ix_graph_edges_temporal", "graph_edges", ["tenant_id","occurred_at"])
    for table in ("graph_entities","graph_edges"):
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"CREATE POLICY {table}_tenant_isolation ON {table} USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"))
    op.execute(sa.text("""
      CREATE FUNCTION validate_entity_evidence_tenant() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE evidence_tenant uuid;
      BEGIN
        IF NEW.evidence_record_id IS NOT NULL THEN
          SELECT tenant_id INTO evidence_tenant FROM evidence_versions WHERE record_id=NEW.evidence_record_id;
          IF evidence_tenant IS NULL OR evidence_tenant <> NEW.tenant_id THEN
            RAISE EXCEPTION 'graph entity evidence tenant mismatch';
          END IF;
        END IF;
        RETURN NEW;
      END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_entity_evidence_tenant BEFORE INSERT OR UPDATE ON graph_entities FOR EACH ROW EXECUTE FUNCTION validate_entity_evidence_tenant()"))
    op.execute(sa.text("""
      CREATE FUNCTION validate_graph_edge_tenant() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE source_tenant uuid; target_tenant uuid;
      BEGIN
        SELECT tenant_id INTO source_tenant FROM graph_entities WHERE entity_id=NEW.source_entity_id;
        SELECT tenant_id INTO target_tenant FROM graph_entities WHERE entity_id=NEW.target_entity_id;
        IF source_tenant IS NULL OR target_tenant IS NULL OR source_tenant <> NEW.tenant_id OR target_tenant <> NEW.tenant_id THEN
          RAISE EXCEPTION 'graph edge endpoint tenant mismatch';
        END IF;
        RETURN NEW;
      END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_graph_edge_tenant BEFORE INSERT OR UPDATE ON graph_edges FOR EACH ROW EXECUTE FUNCTION validate_graph_edge_tenant()"))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_graph_edge_tenant ON graph_edges"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_entity_evidence_tenant ON graph_entities"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_entity_evidence_tenant()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_graph_edge_tenant()"))
    op.drop_table("graph_edges")
    op.drop_table("graph_entities")
