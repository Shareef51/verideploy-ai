"""Deterministic synthetic incident dataset persistence."""
from alembic import op
import sqlalchemy as sa

revision = "0011_milestone29_synthetic_incidents"
down_revision = "0010_milestone28_nexuspay_topology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "synthetic_incidents",
        sa.Column("incident_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("split", sa.String(16), nullable=False),
        sa.Column("failure_mode", sa.String(64), nullable=False),
        sa.Column("primary_service_id", sa.Uuid(), sa.ForeignKey("topology_services.service_id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("topology_environments.environment_id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incident_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("split IN ('train','validation','test')", name="ck_synthetic_incident_split"),
        sa.CheckConstraint("failure_mode IN ('db_pool_exhaustion','incompatible_schema_migration','tls_certificate_expiry','cache_memory_pressure','consumer_lag','downstream_timeout','cpu_saturation','bad_configuration')", name="ck_synthetic_incident_failure_mode"),
        sa.UniqueConstraint("tenant_id", "family_id", name="uq_synthetic_incident_family"),
    )
    op.create_index("ix_synthetic_incident_label_split", "synthetic_incidents", ["tenant_id", "failure_mode", "split"])
    op.create_index("ix_synthetic_incident_service_time", "synthetic_incidents", ["tenant_id", "primary_service_id", "started_at"])
    op.execute(sa.text("ALTER TABLE synthetic_incidents ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE synthetic_incidents FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY synthetic_incidents_tenant_isolation ON synthetic_incidents "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    ))


def downgrade() -> None:
    op.drop_table("synthetic_incidents")
