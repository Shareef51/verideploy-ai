"""Complete RAG and operational database schema."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_milestone32_complete_operational_schema"
down_revision = "0013_milestone31_evidence_graph"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "releases", "pull_requests", "commits", "incidents",
    "investigations", "investigation_checkpoints", "human_reviews",
    "tool_registry", "model_registry", "evaluations", "feedback",
    "jobs", "outbox", "inbox", "audit_events",
)


def _json(default: str = "'{}'::jsonb"):
    return sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text(default))


def _rls(table: str) -> None:
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    ))


def upgrade() -> None:
    op.create_table("releases",
        sa.Column("release_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(48), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _json(),
        sa.CheckConstraint("status IN ('planned','deploying','deployed','failed','rolled_back')", name="ck_release_status"),
        sa.UniqueConstraint("tenant_id","service_id","environment","version",name="uq_release_version"),
    )
    op.create_table("pull_requests",
        sa.Column("pull_request_id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("repository",sa.String(512),nullable=False),sa.Column("number",sa.Integer(),nullable=False),sa.Column("title",sa.String(1024),nullable=False),
        sa.Column("state",sa.String(24),nullable=False),sa.Column("author",sa.String(256),nullable=False),sa.Column("merged_commit_sha",sa.String(64),nullable=True),
        sa.Column("opened_at",sa.DateTime(timezone=True),nullable=False),sa.Column("merged_at",sa.DateTime(timezone=True),nullable=True),_json(),
        sa.CheckConstraint("state IN ('open','closed','merged')",name="ck_pr_state"),
        sa.UniqueConstraint("tenant_id","repository","number",name="uq_pr_repo_number"),
    )
    op.create_table("commits",
        sa.Column("commit_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("repository",sa.String(512),nullable=False),sa.Column("sha",sa.String(64),nullable=False),sa.Column("author",sa.String(256),nullable=False),
        sa.Column("committed_at",sa.DateTime(timezone=True),nullable=False),sa.Column("message",sa.Text(),nullable=False),_json(),
        sa.UniqueConstraint("tenant_id","repository","sha",name="uq_commit_sha"),
    )
    op.create_table("incidents",
        sa.Column("incident_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("external_key",sa.String(256),nullable=False),sa.Column("service_id",sa.Uuid(),nullable=False),sa.Column("severity",sa.String(8),nullable=False),
        sa.Column("status",sa.String(24),nullable=False),sa.Column("started_at",sa.DateTime(timezone=True),nullable=False),sa.Column("resolved_at",sa.DateTime(timezone=True),nullable=True),_json(),
        sa.CheckConstraint("severity IN ('SEV0','SEV1','SEV2','SEV3')",name="ck_incident_severity"),
        sa.CheckConstraint("status IN ('open','mitigating','resolved','closed')",name="ck_incident_status"),
        sa.CheckConstraint("resolved_at IS NULL OR resolved_at >= started_at",name="ck_incident_time"),
        sa.UniqueConstraint("tenant_id","external_key",name="uq_incident_external_key"),
    )
    op.create_table("investigations",
        sa.Column("investigation_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("incident_id",sa.Uuid(),sa.ForeignKey("incidents.incident_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("status",sa.String(32),nullable=False,server_default="created"),sa.Column("version",sa.Integer(),nullable=False,server_default="1"),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),_json(),
        sa.CheckConstraint("version >= 1",name="ck_investigation_version"),
        sa.CheckConstraint("status IN ('created','collecting','waiting_for_evidence','analyzing','review_required','completed','failed','cancelled')",name="ck_investigation_status"),
    )
    op.create_table("investigation_checkpoints",
        sa.Column("checkpoint_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("investigation_id",sa.Uuid(),sa.ForeignKey("investigations.investigation_id",ondelete="CASCADE"),nullable=False),
        sa.Column("sequence",sa.Integer(),nullable=False),sa.Column("state_sha256",sa.String(64),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),_json(),
        sa.CheckConstraint("sequence >= 0",name="ck_checkpoint_sequence"),sa.UniqueConstraint("tenant_id","investigation_id","sequence",name="uq_checkpoint_sequence"),
    )
    op.create_table("human_reviews",
        sa.Column("review_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("investigation_id",sa.Uuid(),sa.ForeignKey("investigations.investigation_id",ondelete="CASCADE"),nullable=False),
        sa.Column("status",sa.String(32),nullable=False,server_default="pending"),sa.Column("reviewer_id",sa.String(256),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("decided_at",sa.DateTime(timezone=True),nullable=True),_json(),
        sa.CheckConstraint("status IN ('pending','in_review','changes_requested','approved','rejected','cancelled')",name="ck_review_status"),
    )
    op.create_table("tool_registry",
        sa.Column("tool_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("name",sa.String(256),nullable=False),sa.Column("version",sa.String(64),nullable=False),sa.Column("risk",sa.String(16),nullable=False),sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.true()),_json(),
        sa.CheckConstraint("risk IN ('low','medium','high','critical')",name="ck_tool_risk"),sa.UniqueConstraint("tenant_id","name","version",name="uq_tool_version"),
    )
    op.create_table("model_registry",
        sa.Column("model_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("provider",sa.String(128),nullable=False),sa.Column("model_name",sa.String(256),nullable=False),sa.Column("role",sa.String(32),nullable=False),sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.true()),_json(),
        sa.CheckConstraint("role IN ('fast','standard','reasoning','embedding','vision')",name="ck_model_role"),sa.UniqueConstraint("tenant_id","provider","model_name","role",name="uq_model_role"),
    )
    op.create_table("evaluations",
        sa.Column("evaluation_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("subject_type",sa.String(64),nullable=False),sa.Column("subject_id",sa.String(256),nullable=False),sa.Column("status",sa.String(24),nullable=False,server_default="queued"),
        sa.Column("score",sa.Float(),nullable=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),_json(),
        sa.CheckConstraint("status IN ('queued','running','passed','failed','cancelled')",name="ck_evaluation_status"),sa.CheckConstraint("score IS NULL OR (score >= 0.0 AND score <= 1.0)",name="ck_evaluation_score"),
    )
    op.create_table("feedback",
        sa.Column("feedback_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("subject_type",sa.String(64),nullable=False),sa.Column("subject_id",sa.String(256),nullable=False),sa.Column("rating",sa.Integer(),nullable=True),sa.Column("comment",sa.Text(),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),_json(),sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)",name="ck_feedback_rating"),
    )
    op.create_table("jobs",
        sa.Column("job_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("job_type",sa.String(128),nullable=False),sa.Column("status",sa.String(24),nullable=False,server_default="queued"),sa.Column("attempt",sa.Integer(),nullable=False,server_default="0"),sa.Column("max_attempts",sa.Integer(),nullable=False,server_default="3"),
        sa.Column("available_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),_json(),
        sa.CheckConstraint("status IN ('queued','running','retry_wait','succeeded','failed','cancelled')",name="ck_job_status"),sa.CheckConstraint("attempt >= 0 AND max_attempts >= 1 AND attempt <= max_attempts",name="ck_job_attempts"),
    )
    op.create_table("outbox",
        sa.Column("outbox_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("topic",sa.String(256),nullable=False),sa.Column("message_key",sa.String(512),nullable=False),sa.Column("idempotency_key",sa.String(256),nullable=False),sa.Column("published_at",sa.DateTime(timezone=True),nullable=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),_json(),
        sa.UniqueConstraint("tenant_id","idempotency_key",name="uq_outbox_idempotency"),
    )
    op.create_table("inbox",
        sa.Column("inbox_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("source",sa.String(256),nullable=False),sa.Column("message_id",sa.String(512),nullable=False),sa.Column("received_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("processed_at",sa.DateTime(timezone=True),nullable=True),_json(),
        sa.UniqueConstraint("tenant_id","source","message_id",name="uq_inbox_message"),
    )
    op.create_table("audit_events",
        sa.Column("audit_id",sa.Uuid(),primary_key=True),sa.Column("tenant_id",sa.Uuid(),sa.ForeignKey("tenants.tenant_id",ondelete="CASCADE"),nullable=False),
        sa.Column("actor_type",sa.String(32),nullable=False),sa.Column("actor_id",sa.String(256),nullable=False),sa.Column("action",sa.String(256),nullable=False),sa.Column("resource_type",sa.String(128),nullable=False),sa.Column("resource_id",sa.String(256),nullable=False),sa.Column("correlation_id",sa.String(256),nullable=False),
        sa.Column("event_sha256",sa.String(64),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),_json(),
        sa.CheckConstraint("actor_type IN ('user','service','agent','system')",name="ck_audit_actor"),sa.UniqueConstraint("tenant_id","event_sha256",name="uq_audit_hash"),
    )

    for table in TENANT_TABLES:
        _rls(table)

    for table, cols in {
        "releases": ["tenant_id","service_id","environment","deployed_at"],
        "pull_requests": ["tenant_id","repository","state"],
        "commits": ["tenant_id","repository","committed_at"],
        "incidents": ["tenant_id","service_id","status","started_at"],
        "investigations": ["tenant_id","incident_id","status","updated_at"],
        "human_reviews": ["tenant_id","investigation_id","status"],
        "evaluations": ["tenant_id","subject_type","status"],
        "jobs": ["tenant_id","status","available_at"],
        "outbox": ["tenant_id","published_at","created_at"],
        "inbox": ["tenant_id","processed_at","received_at"],
        "audit_events": ["tenant_id","resource_type","resource_id","created_at"],
    }.items():
        op.create_index(f"ix_{table}_operational", table, cols)

    op.execute(sa.text(r"""
    CREATE FUNCTION validate_lifecycle_transition() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE ok boolean := false;
    BEGIN
      IF OLD.status = NEW.status THEN RETURN NEW; END IF;
      IF TG_TABLE_NAME = 'investigations' THEN
        ok := (OLD.status='created' AND NEW.status IN ('collecting','cancelled')) OR
              (OLD.status='collecting' AND NEW.status IN ('analyzing','waiting_for_evidence','cancelled','failed')) OR
              (OLD.status='waiting_for_evidence' AND NEW.status IN ('collecting','cancelled','failed')) OR
              (OLD.status='analyzing' AND NEW.status IN ('review_required','completed','failed','cancelled')) OR
              (OLD.status='review_required' AND NEW.status IN ('completed','collecting','cancelled'));
      ELSIF TG_TABLE_NAME = 'human_reviews' THEN
        ok := (OLD.status='pending' AND NEW.status IN ('in_review','cancelled')) OR
              (OLD.status='in_review' AND NEW.status IN ('approved','rejected','changes_requested','cancelled')) OR
              (OLD.status='changes_requested' AND NEW.status IN ('in_review','cancelled'));
      ELSIF TG_TABLE_NAME = 'evaluations' THEN
        ok := (OLD.status='queued' AND NEW.status IN ('running','cancelled')) OR
              (OLD.status='running' AND NEW.status IN ('passed','failed','cancelled'));
      ELSIF TG_TABLE_NAME = 'jobs' THEN
        ok := (OLD.status='queued' AND NEW.status IN ('running','cancelled')) OR
              (OLD.status='running' AND NEW.status IN ('succeeded','failed','retry_wait','cancelled')) OR
              (OLD.status='retry_wait' AND NEW.status IN ('queued','failed','cancelled'));
      END IF;
      IF NOT ok THEN RAISE EXCEPTION USING MESSAGE = 'invalid lifecycle transition on ' || TG_TABLE_NAME || ': ' || OLD.status || ' -> ' || NEW.status; END IF;
      RETURN NEW;
    END; $$
    """))
    for table in ("investigations","human_reviews","evaluations","jobs"):
        op.execute(sa.text(f"CREATE TRIGGER trg_{table}_lifecycle BEFORE UPDATE OF status ON {table} FOR EACH ROW EXECUTE FUNCTION validate_lifecycle_transition()"))

    op.execute(sa.text(r"""
    CREATE FUNCTION validate_tenant_link() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE linked_tenant uuid;
    BEGIN
      IF TG_TABLE_NAME = 'investigations' THEN
        SELECT tenant_id INTO linked_tenant FROM incidents WHERE incident_id=NEW.incident_id;
      ELSE
        SELECT tenant_id INTO linked_tenant FROM investigations WHERE investigation_id=NEW.investigation_id;
      END IF;
      IF linked_tenant IS NULL OR linked_tenant <> NEW.tenant_id THEN
        RAISE EXCEPTION USING MESSAGE = 'tenant link mismatch on ' || TG_TABLE_NAME;
      END IF;
      RETURN NEW;
    END; $$
    """))
    for table in ("investigations","investigation_checkpoints","human_reviews"):
        op.execute(sa.text(f"CREATE TRIGGER trg_{table}_tenant_link BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION validate_tenant_link()"))

    op.execute(sa.text(r"""
    CREATE FUNCTION block_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'audit events are append-only';
    END; $$
    """))
    op.execute(sa.text("CREATE TRIGGER trg_audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION block_audit_mutation()"))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS block_audit_mutation()"))
    for table in ("investigations","investigation_checkpoints","human_reviews"):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_tenant_link ON {table}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_tenant_link()"))
    for table in ("investigations","human_reviews","evaluations","jobs"):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_lifecycle ON {table}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS validate_lifecycle_transition()"))
    for table in reversed(TENANT_TABLES):
        op.drop_table(table)
