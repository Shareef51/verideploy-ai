"""PostgreSQL performance and reliability."""
from alembic import op
import sqlalchemy as sa

revision = "0015_milestone33_postgres_performance_reliability"
down_revision = "0014_milestone32_complete_operational_schema"
branch_labels = None
depends_on = None

PERFORMANCE_INDEXES = (
    ("ix_incidents_open_service_started", "incidents", "tenant_id, service_id, started_at DESC", "status IN ('open','mitigating')"),
    ("ix_investigations_active_updated", "investigations", "tenant_id, updated_at DESC", "status IN ('created','collecting','waiting_for_evidence','analyzing','review_required')"),
    ("ix_jobs_ready", "jobs", "tenant_id, available_at, created_at", "status IN ('queued','retry_wait')"),
    ("ix_outbox_unpublished", "outbox", "tenant_id, created_at, outbox_id", "published_at IS NULL"),
    ("ix_reviews_pending", "human_reviews", "tenant_id, created_at", "status IN ('pending','in_review','changes_requested')"),
    ("ix_retrieval_chunks_source", "retrieval_chunks", "tenant_id, document_id, ordinal", None),
    ("ix_graph_edges_relation_time", "graph_edges", "tenant_id, relationship, occurred_at DESC", None),
    ("ix_evidence_kind_created", "evidence_versions", "tenant_id, kind, created_at DESC", None),
)


def upgrade() -> None:
    # pg_stat_statements still requires the PostgreSQL deployment to preload the module;
    # extension creation is safe and makes schema readiness explicit.
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))

    for name, table, columns, predicate in PERFORMANCE_INDEXES:
        where = f" WHERE {predicate}" if predicate else ""
        op.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns}){where}"))

    # High-volume append-only query telemetry is partitioned by observation time.
    # The DEFAULT partition keeps writes safe until the operator creates monthly partitions.
    op.execute(sa.text("""
    CREATE TABLE database_query_telemetry (
        query_event_id uuid NOT NULL,
        tenant_id uuid NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
        fingerprint char(64) NOT NULL,
        operation varchar(16) NOT NULL,
        duration_ms double precision NOT NULL,
        row_count bigint NULL,
        application_name varchar(128) NOT NULL,
        observed_at timestamptz NOT NULL,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        PRIMARY KEY (query_event_id, observed_at),
        CONSTRAINT ck_query_duration CHECK (duration_ms >= 0)
    ) PARTITION BY RANGE (observed_at)
    """))
    op.execute(sa.text("CREATE TABLE database_query_telemetry_default PARTITION OF database_query_telemetry DEFAULT"))
    op.execute(sa.text("ALTER TABLE database_query_telemetry_default ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE database_query_telemetry_default FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("CREATE POLICY database_query_telemetry_default_tenant_isolation ON database_query_telemetry_default USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"))
    op.execute(sa.text("CREATE INDEX ix_query_telemetry_tenant_time ON database_query_telemetry (tenant_id, observed_at DESC)"))
    op.execute(sa.text("CREATE INDEX ix_query_telemetry_fingerprint ON database_query_telemetry (tenant_id, fingerprint, observed_at DESC)"))
    op.execute(sa.text("ALTER TABLE database_query_telemetry ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE database_query_telemetry FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("CREATE POLICY database_query_telemetry_tenant_isolation ON database_query_telemetry USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS database_query_telemetry CASCADE"))
    for name, _table, _columns, _predicate in reversed(PERFORMANCE_INDEXES):
        op.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
    # pg_stat_statements may be shared with other applications; do not drop the extension.
