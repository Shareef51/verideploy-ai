"""NexusPay service topology persistence."""
from alembic import op
import sqlalchemy as sa

revision = "0010_milestone28_nexuspay_topology"
down_revision = "0009_milestone25_mcp_gateway"
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
        "topology_companies",
        sa.Column("company_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("seed_version", sa.String(80), nullable=False),
        sa.Column("seed_sha256", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_topology_company_tenant_slug"),
    )
    op.create_table(
        "topology_teams",
        sa.Column("team_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("topology_companies.company_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("slug", sa.String(80), nullable=False), sa.Column("mission", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_topology_team_tenant_slug"),
    )
    op.create_table(
        "topology_owners",
        sa.Column("owner_id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("topology_teams.team_id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False), sa.Column("role", sa.String(160), nullable=False), sa.Column("oncall_alias", sa.String(120), nullable=False),
    )
    op.create_table(
        "topology_environments",
        sa.Column("environment_id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(32), nullable=False), sa.Column("region", sa.String(80), nullable=False), sa.Column("criticality", sa.String(20), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_topology_environment_tenant_name"),
        sa.CheckConstraint("criticality IN ('critical','high','medium','low')", name="ck_topology_environment_criticality"),
    )
    op.create_table(
        "topology_services",
        sa.Column("service_id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("topology_teams.team_id", ondelete="RESTRICT"), nullable=False), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False), sa.Column("domain", sa.String(120), nullable=False), sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("runtime", sa.String(80), nullable=False), sa.Column("repository", sa.String(200), nullable=False), sa.Column("description", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_topology_service_tenant_slug"), sa.CheckConstraint("tier IN ('tier_0','tier_1','tier_2')", name="ck_topology_service_tier"),
    )
    op.create_table(
        "topology_dependencies",
        sa.Column("dependency_id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_service_id", sa.Uuid(), sa.ForeignKey("topology_services.service_id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_service_id", sa.Uuid(), sa.ForeignKey("topology_services.service_id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False), sa.Column("criticality", sa.String(20), nullable=False), sa.Column("description", sa.Text(), nullable=False),
        sa.CheckConstraint("source_service_id <> target_service_id", name="ck_topology_dependency_not_self"),
        sa.CheckConstraint("kind IN ('sync_http','async_event','data','telemetry')", name="ck_topology_dependency_kind"),
        sa.CheckConstraint("criticality IN ('critical','high','medium','low')", name="ck_topology_dependency_criticality"),
        sa.UniqueConstraint("tenant_id", "source_service_id", "target_service_id", "kind", name="uq_topology_dependency_edge_kind"),
    )
    op.create_table(
        "topology_slos",
        sa.Column("slo_id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.Uuid(), sa.ForeignKey("topology_services.service_id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("topology_environments.environment_id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(40), nullable=False), sa.Column("target", sa.Float(), nullable=False), sa.Column("window_days", sa.Integer(), nullable=False),
        sa.CheckConstraint("target > 0", name="ck_topology_slo_target_positive"), sa.CheckConstraint("window_days BETWEEN 1 AND 90", name="ck_topology_slo_window"),
        sa.UniqueConstraint("tenant_id", "service_id", "environment_id", "metric", name="uq_topology_slo_metric"),
    )
    op.create_table(
        "topology_deployments",
        sa.Column("deployment_id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.Uuid(), sa.ForeignKey("topology_services.service_id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("topology_environments.environment_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(120), nullable=False), sa.Column("commit_sha", sa.String(40), nullable=False), sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cluster", sa.String(160), nullable=False), sa.Column("namespace", sa.String(160), nullable=False), sa.Column("replicas", sa.Integer(), nullable=False),
        sa.CheckConstraint("replicas > 0", name="ck_topology_deployment_replicas_positive"),
        sa.UniqueConstraint("tenant_id", "service_id", "environment_id", "version", name="uq_topology_deployment_version"),
    )
    for table in ("topology_companies","topology_teams","topology_owners","topology_environments","topology_services","topology_dependencies","topology_slos","topology_deployments"):
        _rls(table)
    op.create_index("ix_topology_service_team", "topology_services", ["tenant_id","team_id"])
    op.create_index("ix_topology_dependency_source", "topology_dependencies", ["tenant_id","source_service_id"])
    op.create_index("ix_topology_dependency_target", "topology_dependencies", ["tenant_id","target_service_id"])
    op.create_index("ix_topology_deployment_environment", "topology_deployments", ["tenant_id","environment_id","deployed_at"])


def downgrade() -> None:
    for table in ("topology_deployments","topology_slos","topology_dependencies","topology_services","topology_environments","topology_owners","topology_teams","topology_companies"):
        op.drop_table(table)
